"""Curated openQA MCP tools.

Each tool is a thin, typed wrapper over ``AsyncOpenQAClient.openqa_request``:
it drops ``None`` params and returns the parsed dict/list body. One-line
docstrings become the MCP tool descriptions. Mutating tools are tagged
``mutating`` and require API credentials (openQA answers ``403`` without them).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from fastmcp import Context, FastMCP
from openqa_async.aclient import AsyncOpenQAClient

from .client import AppContext, lifespan

#: Tag marking tools that mutate openQA state; stripped in read-only mode.
MUTATING_TAG = "mutating"

mcp = FastMCP(
    "openQA",
    instructions=(
        "Query and control an openQA instance. Read tools inspect jobs, "
        "machines, test suites, and products; mutating tools (tagged "
        "'mutating') restart/cancel/delete jobs, comment, and trigger ISOs, "
        "and require API credentials."
    ),
    lifespan=lifespan,
)


def _client(ctx: Context) -> AsyncOpenQAClient:
    """Return the shared client from the lifespan context."""
    return cast(AppContext, ctx.lifespan_context).client


def _drop_none(params: dict[str, Any]) -> dict[str, Any]:
    """Strip keys whose value is ``None`` so they are not sent as query params."""
    return {k: v for k, v in params.items() if v is not None}


def _api(path: str) -> str:
    """Prefix a REST endpoint with ``api/v1/``.

    ``openqa-async`` joins request paths straight onto the server host, so
    the ``/api/v1`` prefix that fronts every REST endpoint must be supplied
    here; without it requests hit non-existent web-UI routes and 404.
    """
    return f"api/v1/{path}"


# --------------------------------------------------------------------------- #
# READ tools                                                                   #
# --------------------------------------------------------------------------- #


@mcp.tool
async def list_jobs(
    ctx: Context,
    state: str | None = None,
    result: str | None = None,
    distri: str | None = None,
    version: str | None = None,
    build: str | None = None,
    test: str | None = None,
    arch: str | None = None,
    machine: str | None = None,
    groupid: int | None = None,
    group: str | None = None,
    latest: int | None = None,
    limit: int | None = None,
    page: int | None = None,
    ids: list[int] | None = None,
) -> dict | list:
    """List jobs matching the given filters."""
    params = _drop_none(
        {
            "state": state,
            "result": result,
            "distri": distri,
            "version": version,
            "build": build,
            "test": test,
            "arch": arch,
            "machine": machine,
            "groupid": groupid,
            "group": group,
            "latest": latest,
            "limit": limit,
            "page": page,
            "ids": ids,
        }
    )
    return await _client(ctx).openqa_request("GET", _api("jobs"), params=params)


@mcp.tool
async def list_jobs_overview(
    ctx: Context,
    state: str | None = None,
    result: str | None = None,
    distri: str | None = None,
    version: str | None = None,
    build: str | None = None,
    test: str | None = None,
    arch: str | None = None,
    machine: str | None = None,
    groupid: int | None = None,
    group: str | None = None,
    latest: int | None = None,
    limit: int | None = None,
    page: int | None = None,
    ids: list[int] | None = None,
) -> dict | list:
    """List a condensed jobs overview matching the given filters."""
    params = _drop_none(
        {
            "state": state,
            "result": result,
            "distri": distri,
            "version": version,
            "build": build,
            "test": test,
            "arch": arch,
            "machine": machine,
            "groupid": groupid,
            "group": group,
            "latest": latest,
            "limit": limit,
            "page": page,
            "ids": ids,
        }
    )
    return await _client(ctx).openqa_request(
        "GET", _api("jobs/overview"), params=params
    )


@mcp.tool
async def get_job(ctx: Context, job_id: int) -> dict | list:
    """Get full details for a single job."""
    return await _client(ctx).openqa_request("GET", _api(f"jobs/{job_id}"))


@mcp.tool
async def get_job_comments(ctx: Context, job_id: int) -> dict | list:
    """List comments on a job."""
    return await _client(ctx).openqa_request("GET", _api(f"jobs/{job_id}/comments"))


@mcp.tool
async def list_machines(ctx: Context) -> dict | list:
    """List configured worker machines."""
    return await _client(ctx).openqa_request("GET", _api("machines"))


@mcp.tool
async def list_test_suites(ctx: Context) -> dict | list:
    """List configured test suites."""
    return await _client(ctx).openqa_request("GET", _api("test_suites"))


@mcp.tool
async def list_products(ctx: Context) -> dict | list:
    """List configured products (mediums)."""
    return await _client(ctx).openqa_request("GET", _api("products"))


@mcp.tool
async def find_jobs_by_setting(ctx: Context, key: str, list_value: str) -> dict | list:
    """Find jobs whose setting ``key`` equals ``list_value``."""
    params = {"key": key, "list_value": list_value}
    return await _client(ctx).openqa_request(
        "GET", _api("job_settings/jobs"), params=params
    )


# --------------------------------------------------------------------------- #
# MUTATING tools (require credentials; 403 without)                            #
# --------------------------------------------------------------------------- #


@mcp.tool(tags={MUTATING_TAG})
async def restart_jobs(ctx: Context, job_ids: list[int]) -> list:
    """Restart each of the given jobs (requires credentials)."""
    client = _client(ctx)
    results = []
    for job_id in job_ids:
        results.append(
            await client.openqa_request("POST", _api(f"jobs/{job_id}/restart"))
        )
    return results


@mcp.tool(tags={MUTATING_TAG})
async def cancel_job(ctx: Context, job_id: int) -> dict | list:
    """Cancel a running or scheduled job (requires credentials)."""
    return await _client(ctx).openqa_request("POST", _api(f"jobs/{job_id}/cancel"))


@mcp.tool(tags={MUTATING_TAG})
async def add_job_comment(ctx: Context, job_id: int, text: str) -> dict | list:
    """Add a comment to a job (requires credentials)."""
    return await _client(ctx).openqa_request(
        "POST", _api(f"jobs/{job_id}/comments"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def trigger_isos(
    ctx: Context,
    distri: str,
    version: str,
    flavor: str,
    arch: str,
    extra: dict[str, str] | None = None,
) -> dict | list:
    """Trigger ISO test scheduling for a product (requires credentials)."""
    body = {"DISTRI": distri, "VERSION": version, "FLAVOR": flavor, "ARCH": arch}
    if extra:
        body.update(extra)
    return await _client(ctx).openqa_request("POST", _api("isos"), data=body)


@mcp.tool(tags={MUTATING_TAG})
async def delete_job(ctx: Context, job_id: int) -> dict | list:
    """Delete a job (requires credentials)."""
    result = await _client(ctx).openqa_request("DELETE", _api(f"jobs/{job_id}"))
    # A 204 No Content yields a raw httpx Response, not a dict/list; normalize.
    return result if isinstance(result, (dict, list)) else {}


def disable_mutating_tools() -> list[str]:
    """Unregister every tool tagged ``mutating`` (read-only mode).

    ``FastMCP.list_tools`` is a coroutine but does no real I/O here, so it is
    safe to drive with ``asyncio.run`` from the synchronous CLI before
    ``mcp.run`` starts its own event loop. Returns the removed tool names.
    """
    tools = asyncio.run(mcp.list_tools())
    removed = [t.name for t in tools if MUTATING_TAG in t.tags]
    for name in removed:
        mcp.local_provider.remove_tool(name)
    return removed
