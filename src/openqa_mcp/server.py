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


@mcp.tool
async def get_job_details(ctx: Context, job_id: int) -> dict | list:
    """Get a single job with full test-module/step details."""
    return await _client(ctx).openqa_request("GET", _api(f"jobs/{job_id}/details"))


@mcp.tool
async def get_job_status(
    ctx: Context, job_id: int, follow: int | None = None
) -> dict | list:
    """Get a lightweight job status (id, state, result, blocked_by_id)."""
    params = _drop_none({"follow": follow})
    return await _client(ctx).openqa_request(
        "GET", _api(f"experimental/jobs/{job_id}/status"), params=params
    )


@mcp.tool
async def list_job_groups(ctx: Context) -> dict | list:
    """List job groups."""
    return await _client(ctx).openqa_request("GET", _api("job_groups"))


@mcp.tool
async def get_job_group(ctx: Context, group_id: int) -> dict | list:
    """Get a single job group."""
    return await _client(ctx).openqa_request("GET", _api(f"job_groups/{group_id}"))


@mcp.tool
async def list_job_group_jobs(ctx: Context, group_id: int) -> dict | list:
    """List jobs belonging to a job group."""
    return await _client(ctx).openqa_request("GET", _api(f"job_groups/{group_id}/jobs"))


@mcp.tool
async def get_job_group_build_results(
    ctx: Context,
    group_id: int,
    limit_builds: int | None = None,
    time_limit_days: float | None = None,
    only_tagged: int | None = None,
    show_tags: int | None = None,
) -> dict | list:
    """Get aggregated build results for a job group."""
    params = _drop_none(
        {
            "limit_builds": limit_builds,
            "time_limit_days": time_limit_days,
            "only_tagged": only_tagged,
            "show_tags": show_tags,
        }
    )
    return await _client(ctx).openqa_request(
        "GET", _api(f"job_groups/{group_id}/build_results"), params=params
    )


@mcp.tool
async def list_parent_groups(ctx: Context) -> dict | list:
    """List parent job groups."""
    return await _client(ctx).openqa_request("GET", _api("parent_groups"))


@mcp.tool
async def get_parent_group(ctx: Context, group_id: int) -> dict | list:
    """Get a single parent job group."""
    return await _client(ctx).openqa_request("GET", _api(f"parent_groups/{group_id}"))


@mcp.tool
async def list_assets(ctx: Context) -> dict | list:
    """List assets known to the system."""
    return await _client(ctx).openqa_request("GET", _api("assets"))


@mcp.tool
async def get_asset(ctx: Context, asset_id: int) -> dict | list:
    """Get a single asset by id."""
    return await _client(ctx).openqa_request("GET", _api(f"assets/{asset_id}"))


@mcp.tool
async def list_workers(ctx: Context) -> dict | list:
    """List registered worker instances."""
    return await _client(ctx).openqa_request("GET", _api("workers"))


@mcp.tool
async def list_bugs(ctx: Context) -> dict | list:
    """List tracked bugs referenced by jobs."""
    return await _client(ctx).openqa_request("GET", _api("bugs"))


@mcp.tool
async def search(ctx: Context, q: str) -> dict | list:
    """Full-text search across jobs, groups, and test modules."""
    return await _client(ctx).openqa_request(
        "GET", _api("experimental/search"), params={"q": q}
    )


@mcp.tool
async def whoami(ctx: Context) -> dict | list:
    """Return the identity associated with the current credentials."""
    return await _client(ctx).openqa_request("GET", _api("whoami"))


@mcp.tool
async def get_scheduled_product(ctx: Context, scheduled_product_id: int) -> dict | list:
    """Get a scheduled product (result of a prior ISO trigger)."""
    return await _client(ctx).openqa_request(
        "GET", _api(f"isos/{scheduled_product_id}")
    )


@mcp.tool
async def get_iso_job_stats(ctx: Context) -> dict | list:
    """Get job statistics for scheduled products."""
    return await _client(ctx).openqa_request("GET", _api("isos/job_stats"))


@mcp.tool
async def list_group_comments(ctx: Context, group_id: int) -> dict | list:
    """List comments on a job group."""
    return await _client(ctx).openqa_request("GET", _api(f"groups/{group_id}/comments"))


@mcp.tool
async def list_parent_group_comments(ctx: Context, parent_group_id: int) -> dict | list:
    """List comments on a parent job group."""
    return await _client(ctx).openqa_request(
        "GET", _api(f"parent_groups/{parent_group_id}/comments")
    )


# --------------------------------------------------------------------------- #
# MUTATING tools (require credentials; 403 without)                            #
# --------------------------------------------------------------------------- #


@mcp.tool(tags={MUTATING_TAG})
async def restart_jobs(ctx: Context, job_ids: list[int]) -> list:
    """Restart each of the given jobs."""
    client = _client(ctx)
    results = []
    for job_id in job_ids:
        results.append(
            await client.openqa_request("POST", _api(f"jobs/{job_id}/restart"))
        )
    return results


@mcp.tool(tags={MUTATING_TAG})
async def cancel_job(ctx: Context, job_id: int) -> dict | list:
    """Cancel a running or scheduled job."""
    return await _client(ctx).openqa_request("POST", _api(f"jobs/{job_id}/cancel"))


@mcp.tool(tags={MUTATING_TAG})
async def add_job_comment(ctx: Context, job_id: int, text: str) -> dict | list:
    """Add a comment to a job."""
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
    """Trigger ISO test scheduling for a product."""
    body = {"DISTRI": distri, "VERSION": version, "FLAVOR": flavor, "ARCH": arch}
    if extra:
        body.update(extra)
    return await _client(ctx).openqa_request("POST", _api("isos"), data=body)


@mcp.tool(tags={MUTATING_TAG})
async def delete_job(ctx: Context, job_id: int) -> dict | list:
    """Delete a job."""
    result = await _client(ctx).openqa_request("DELETE", _api(f"jobs/{job_id}"))
    # A 204 No Content yields a raw httpx Response, not a dict/list; normalize.
    return result if isinstance(result, (dict, list)) else {}


@mcp.tool(tags={MUTATING_TAG})
async def duplicate_job(
    ctx: Context,
    job_id: int,
    prio: int | None = None,
    dup_type_auto: int | None = None,
) -> dict | list:
    """Duplicate (clone) a job."""
    data = _drop_none({"prio": prio, "dup_type_auto": dup_type_auto})
    return await _client(ctx).openqa_request(
        "POST", _api(f"jobs/{job_id}/duplicate"), data=data
    )


@mcp.tool(tags={MUTATING_TAG})
async def set_job_priority(ctx: Context, job_id: int, prio: int) -> dict | list:
    """Set the priority of a job."""
    return await _client(ctx).openqa_request(
        "POST", _api(f"jobs/{job_id}/prio"), data={"prio": prio}
    )


@mcp.tool(tags={MUTATING_TAG})
async def restart_jobs_bulk(
    ctx: Context,
    job_ids: list[int],
    force: int | None = None,
    prio: int | None = None,
) -> dict | list:
    """Restart several jobs in one bulk request."""
    data = _drop_none({"jobs": job_ids, "force": force, "prio": prio})
    return await _client(ctx).openqa_request("POST", _api("jobs/restart"), data=data)


@mcp.tool(tags={MUTATING_TAG})
async def cancel_jobs(
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
) -> dict | list:
    """Cancel all jobs matching the given filters."""
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
        }
    )
    return await _client(ctx).openqa_request("POST", _api("jobs/cancel"), params=params)


@mcp.tool(tags={MUTATING_TAG})
async def add_group_comment(ctx: Context, group_id: int, text: str) -> dict | list:
    """Add a comment to a job group."""
    return await _client(ctx).openqa_request(
        "POST", _api(f"groups/{group_id}/comments"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def add_parent_group_comment(
    ctx: Context, parent_group_id: int, text: str
) -> dict | list:
    """Add a comment to a parent job group."""
    return await _client(ctx).openqa_request(
        "POST", _api(f"parent_groups/{parent_group_id}/comments"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def update_job_comment(
    ctx: Context, job_id: int, comment_id: int, text: str
) -> dict | list:
    """Update an existing job comment."""
    return await _client(ctx).openqa_request(
        "PUT", _api(f"jobs/{job_id}/comments/{comment_id}"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def delete_job_comment(ctx: Context, job_id: int, comment_id: int) -> dict | list:
    """Delete a job comment."""
    result = await _client(ctx).openqa_request(
        "DELETE", _api(f"jobs/{job_id}/comments/{comment_id}")
    )
    # A 204 No Content yields a raw httpx Response, not a dict/list; normalize.
    return result if isinstance(result, (dict, list)) else {}


@mcp.tool(tags={MUTATING_TAG})
async def create_bug(ctx: Context, bugid: str, title: str | None = None) -> dict | list:
    """Create a tracked bug reference."""
    data = _drop_none({"bugid": bugid, "title": title})
    return await _client(ctx).openqa_request("POST", _api("bugs"), data=data)


@mcp.tool(tags={MUTATING_TAG})
async def cancel_scheduled_product(ctx: Context, name: str) -> dict | list:
    """Cancel a scheduled product / ISO by name."""
    return await _client(ctx).openqa_request("POST", _api(f"isos/{name}/cancel"))


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
