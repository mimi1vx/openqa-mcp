"""Shared ``AsyncOpenQAClient`` construction and FastMCP lifespan wiring.

``get_client`` builds a client from environment configuration, optionally
overriding the API credentials baked in by ``openqa-async``'s config-file
loading. ``lifespan`` exposes a single shared client to the server for the
duration of its run.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from openqa_async.aclient import AsyncOpenQAClient

_FALSE_TOKENS = frozenset({"0", "false", "no"})
_TRUE_TOKENS = frozenset({"1", "true", "yes"})


def _parse_verify(raw: str | None) -> bool | str:
    """Map ``OPENQA_VERIFY`` to an httpx ``verify`` value.

    Bool-ish tokens toggle verification; any other non-empty value is
    treated as a path to a CA bundle. Unset defaults to ``True``.
    """
    if raw is None:
        return True
    token = raw.strip()
    lowered = token.lower()
    if lowered in _FALSE_TOKENS:
        return False
    if lowered in _TRUE_TOKENS:
        return True
    if token:
        return token  # CA bundle path
    return True


def _parse_timeout(raw: str | None) -> httpx.Timeout:
    """Map ``OPENQA_MCP_TIMEOUT`` to an httpx ``Timeout``.

    Unset defaults to 30s (headroom for slow ``latest=1`` failed-job queries,
    which openqa-async's underlying 5s httpx default kills). ``<=0`` disables
    the timeout entirely; malformed values fall back to the default.
    """
    default = 30.0
    if raw is None:
        return httpx.Timeout(default)
    try:
        value = float(raw)
    except ValueError:
        return httpx.Timeout(default)
    if value <= 0:
        return httpx.Timeout(None)
    return httpx.Timeout(value)


def _apply_env_credentials(client: AsyncOpenQAClient) -> None:
    """Override the client's API credentials from the environment.

    Only applied when both ``OPENQA_API_KEY`` and ``OPENQA_API_SECRET``
    are set, avoiding a half-configured client that signs with an empty
    secret.

    NOTE (library-internal touch-point): ``AsyncOpenQAClient`` bakes auth
    into ``self.client`` at construction time -- the httpx client's static
    ``X-API-Key`` header comes from ``_apikey`` via ``_default_headers()``
    and the HMAC auth from ``apisecret`` via ``_build_auth()``. Assigning
    the credentials alone does nothing until ``client.client`` is rebuilt
    the same way the constructor does. Keep this the only place that
    reaches into these private attributes; prefer ``client.conf`` in docs.
    """
    api_key = os.environ.get("OPENQA_API_KEY")
    api_secret = os.environ.get("OPENQA_API_SECRET")
    if not (api_key and api_secret):
        return

    client._apikey = api_key
    client.apisecret = api_secret
    client.client = httpx.AsyncClient(
        base_url=client.baseurl,
        headers=client._default_headers(),
        auth=client._build_auth(),
        trust_env=True,
        verify=client.verify,
    )


def get_client() -> AsyncOpenQAClient:
    """Build a shared ``AsyncOpenQAClient`` from environment configuration.

    Reads ``OPENQA_SERVER`` (empty falls back to the openqa-async default),
    ``OPENQA_VERIFY``, ``OPENQA_MCP_TIMEOUT``, and optionally ``OPENQA_API_KEY``
    / ``OPENQA_API_SECRET`` to override config-file credentials.
    """
    server = os.environ.get("OPENQA_SERVER", "")
    verify = _parse_verify(os.environ.get("OPENQA_VERIFY"))
    client = AsyncOpenQAClient(server=server, verify=verify)
    _apply_env_credentials(client)
    # openqa-async 0.1.0 builds its httpx client with no timeout (httpx's 5s
    # default kills slow queries) and exposes no knob for it. Override after
    # _apply_env_credentials so it also covers the client it may rebuild.
    # NOTE: like _apply_env_credentials, this reaches into client.client on
    # purpose; keep timeout wiring here until openqa-async accepts `timeout`.
    client.client.timeout = _parse_timeout(os.environ.get("OPENQA_MCP_TIMEOUT"))
    return client


@dataclass
class AppContext:
    """Shared state made available to tools for the server's lifetime."""

    client: AsyncOpenQAClient


@asynccontextmanager
async def lifespan(server: object) -> AsyncIterator[AppContext]:
    """Open a single shared client on startup, close it on shutdown."""
    client = get_client()
    try:
        yield AppContext(client=client)
    finally:
        await client.aclose()
