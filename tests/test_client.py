"""Tests for the client factory + env-credential override."""

import httpx
import pytest

from openqa_async.aclient import AsyncOpenQAClient
from openqa_async._auth import OpenQAAuth

from openqa_mcp.client import AppContext, _parse_verify, get_client, lifespan


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate each test from ambient openQA env configuration."""
    for var in (
        "OPENQA_SERVER",
        "OPENQA_VERIFY",
        "OPENQA_API_KEY",
        "OPENQA_API_SECRET",
        "OPENQA_MCP_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    # Pin a non-local server so config-file creds never leak into tests.
    monkeypatch.setenv("OPENQA_SERVER", "openqa.example.com")


def test_env_credentials_land_in_httpx_client(monkeypatch):
    monkeypatch.setenv("OPENQA_API_KEY", "DEADBEEF")
    monkeypatch.setenv("OPENQA_API_SECRET", "C0FFEE")

    client = get_client()

    assert client.client.headers["X-API-Key"] == "DEADBEEF"
    assert isinstance(client.client.auth, OpenQAAuth)
    assert client.client.auth.apisecret == "C0FFEE"
    assert client._apikey == "DEADBEEF"
    assert client.apisecret == "C0FFEE"


def test_no_env_credentials_means_no_api_key_header():
    client = get_client()

    assert "X-API-Key" not in client.client.headers


def test_partial_credentials_do_not_override(monkeypatch):
    # Key without secret must not produce a half-configured client.
    monkeypatch.setenv("OPENQA_API_KEY", "DEADBEEF")

    client = get_client()

    assert "X-API-Key" not in client.client.headers
    assert client._apikey == ""


def test_verify_false_disables_verification(monkeypatch):
    monkeypatch.setenv("OPENQA_VERIFY", "false")

    client = get_client()

    assert client.verify is False


def test_verify_defaults_to_true():
    client = get_client()

    assert client.verify is True


def test_verify_path_passed_through():
    # A non-bool token is treated as a CA bundle path. Asserted at the
    # parser level: get_client would eagerly load the bundle via httpx,
    # which requires a real cert file unrelated to this mapping.
    assert _parse_verify("/etc/ssl/custom-ca.pem") == "/etc/ssl/custom-ca.pem"


def test_timeout_defaults_to_30():
    client = get_client()

    assert client.client.timeout == httpx.Timeout(30.0)


def test_timeout_from_env(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_TIMEOUT", "60")

    client = get_client()

    assert client.client.timeout == httpx.Timeout(60.0)


def test_timeout_zero_disables(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_TIMEOUT", "0")

    client = get_client()

    assert client.client.timeout == httpx.Timeout(None)


def test_timeout_malformed_falls_back(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_TIMEOUT", "abc")

    client = get_client()

    assert client.client.timeout == httpx.Timeout(30.0)


def test_timeout_applies_with_credentials(monkeypatch):
    # The timeout override runs after _apply_env_credentials rebuilds the
    # httpx client, so it must survive that rebuild.
    monkeypatch.setenv("OPENQA_API_KEY", "DEADBEEF")
    monkeypatch.setenv("OPENQA_API_SECRET", "C0FFEE")
    monkeypatch.setenv("OPENQA_MCP_TIMEOUT", "60")

    client = get_client()

    assert client.client.headers["X-API-Key"] == "DEADBEEF"
    assert client.client.timeout == httpx.Timeout(60.0)


@pytest.mark.asyncio
async def test_lifespan_yields_shared_client_and_closes():
    async with lifespan(server=object()) as ctx:
        assert isinstance(ctx, AppContext)
        assert isinstance(ctx.client, AsyncOpenQAClient)
        client = ctx.client

    # httpx marks the client closed after aclose().
    assert client.client.is_closed
