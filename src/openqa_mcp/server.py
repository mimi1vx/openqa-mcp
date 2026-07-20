"""Curated openQA MCP tools.

Each tool is a thin, typed wrapper over ``AsyncOpenQAClient.openqa_request``:
it drops ``None`` params and returns the parsed dict/list body. One-line
docstrings become the MCP tool descriptions. Mutating tools are tagged
``mutating`` and require API credentials (openQA answers ``403`` without them).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from typing import Any, TypeVar, cast

from fastmcp import Context, FastMCP
from openqa_async.aclient import AsyncOpenQAClient

from .client import AppContext, lifespan

#: Tag marking tools that mutate openQA state; stripped in read-only mode.
MUTATING_TAG = "mutating"


def _heartbeat_interval() -> float:
    """Seconds between heartbeat pings; ``<=0`` disables the heartbeat.

    Read from ``OPENQA_MCP_HEARTBEAT_INTERVAL`` on each request so tests can
    tweak it via ``monkeypatch``; malformed values fall back to the default.
    """
    raw = os.environ.get("OPENQA_MCP_HEARTBEAT_INTERVAL")
    if raw is None:
        return 15.0
    try:
        return float(raw)
    except ValueError:
        return 15.0


_T = TypeVar("_T")

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


def _summarize_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a raw openQA ``jobs`` array into a compact triage summary.

    The raw array is ~10 KB/job (assets/modules/settings/…) and truncates in MCP
    clients; this keeps only id/test/arch per job plus counts. Each job buckets
    by its ``result`` when that is truthy and not ``"none"``, otherwise by its
    ``state`` (so in-progress jobs land under ``running``/``scheduled`` rather
    than a ``"none"`` catch-all); a job lacking both falls under ``"unknown"``.
    """
    by_result: dict[str, int] = {}
    by_state: dict[str, int] = {}
    by_arch: dict[str, int] = {}
    buckets: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        result = job.get("result")
        state = job.get("state")
        key = result if result and result != "none" else state
        key = key or "unknown"
        buckets.setdefault(key, []).append(
            {
                "id": job.get("id"),
                "test": job.get("test"),
                "arch": (job.get("settings") or {}).get("ARCH"),
            }
        )
        if result:
            by_result[result] = by_result.get(result, 0) + 1
        if state:
            by_state[state] = by_state.get(state, 0) + 1
        arch = (job.get("settings") or {}).get("ARCH")
        if arch:
            by_arch[arch] = by_arch.get(arch, 0) + 1
    return {
        "total": len(jobs),
        "by_result": by_result,
        "by_state": by_state,
        "by_arch": by_arch,
        "jobs": buckets,
    }


async def _with_heartbeat(ctx: Context, coro: Awaitable[_T]) -> _T:
    """Run ``coro`` while emitting periodic progress pings to keep clients alive.

    A background ticker calls ``ctx.report_progress`` every
    ``OPENQA_MCP_HEARTBEAT_INTERVAL`` seconds (indeterminate progress: a rising
    counter, no ``total``) so an MCP client waiting on a slow REST call sees
    liveness instead of timing out. ``report_progress`` is a no-op unless the
    client supplied a ``progressToken``. Ping failures are swallowed so they
    never leak into the tool result. The ticker is always cancelled and awaited
    in ``finally`` to avoid a leaked/pending task. Interval ``<=0`` disables it.
    """
    interval = _heartbeat_interval()
    if interval <= 0:
        return await coro

    async def _ticker() -> None:
        progress = 0.0
        while True:
            await asyncio.sleep(interval)
            progress += 1
            try:
                await ctx.report_progress(progress, message="working…")
            except Exception:
                pass

    ticker = asyncio.create_task(_ticker())
    try:
        return await coro
    finally:
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass


async def _request(ctx: Context, method: str, path: str, **kwargs: Any) -> Any:
    """Issue an openQA REST request under a heartbeat.

    Single funnel for every tool: routes ``AsyncOpenQAClient.openqa_request``
    through ``_with_heartbeat`` so all tools get liveness pings without changing
    their signatures or the request itself.
    """
    return await _with_heartbeat(
        ctx, _client(ctx).openqa_request(method, path, **kwargs)
    )


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
    summary: bool = False,
) -> dict | list:
    """List jobs matching the given filters.

    WARNING: the full result can be very large (~1.5 MB / 150+ jobs for a
    populated build) and may be truncated by MCP clients. For triage, pass
    summary=True for a compact per-result breakdown. To work with the full data,
    save it to a temporary file and process it with jq, e.g.
    `jq '.jobs[] | select(.result=="failed")'`.
    """
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
    body = await _request(ctx, "GET", _api("jobs"), params=params)
    if summary and isinstance(body, dict):
        return _summarize_jobs(body.get("jobs") or [])
    return body


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
    summary: bool = False,
) -> dict | list:
    """List a condensed jobs overview matching the given filters.

    WARNING: the full result can be very large (~1.5 MB / 150+ jobs for a
    populated build) and may be truncated by MCP clients. For triage, pass
    summary=True for a compact per-result breakdown. To work with the full data,
    save it to a temporary file and process it with jq, e.g.
    `jq '.jobs[] | select(.result=="failed")'`.
    """
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
    body = await _request(ctx, "GET", _api("jobs/overview"), params=params)
    if summary:
        jobs = body.get("jobs") if isinstance(body, dict) else body
        return _summarize_jobs(jobs or [])
    return body


@mcp.tool
async def get_job(ctx: Context, job_id: int) -> dict | list:
    """Get full details for a single job."""
    return await _request(ctx, "GET", _api(f"jobs/{job_id}"))


@mcp.tool
async def get_job_comments(ctx: Context, job_id: int) -> dict | list:
    """List comments on a job."""
    return await _request(ctx, "GET", _api(f"jobs/{job_id}/comments"))


@mcp.tool
async def list_machines(ctx: Context) -> dict | list:
    """List configured worker machines."""
    return await _request(ctx, "GET", _api("machines"))


@mcp.tool
async def list_test_suites(ctx: Context) -> dict | list:
    """List configured test suites."""
    return await _request(ctx, "GET", _api("test_suites"))


@mcp.tool
async def list_products(ctx: Context) -> dict | list:
    """List configured products (mediums)."""
    return await _request(ctx, "GET", _api("products"))


@mcp.tool
async def find_jobs_by_setting(ctx: Context, key: str, list_value: str) -> dict | list:
    """Find jobs whose setting ``key`` equals ``list_value``."""
    params = {"key": key, "list_value": list_value}
    return await _request(ctx, "GET", _api("job_settings/jobs"), params=params)


@mcp.tool
async def get_job_details(ctx: Context, job_id: int) -> dict | list:
    """Get a single job with full test-module/step details."""
    return await _request(ctx, "GET", _api(f"jobs/{job_id}/details"))


@mcp.tool
async def get_job_status(
    ctx: Context, job_id: int, follow: int | None = None
) -> dict | list:
    """Get a lightweight job status (id, state, result, blocked_by_id)."""
    params = _drop_none({"follow": follow})
    return await _request(
        ctx, "GET", _api(f"experimental/jobs/{job_id}/status"), params=params
    )


@mcp.tool
async def list_job_groups(ctx: Context) -> dict | list:
    """List job groups."""
    return await _request(ctx, "GET", _api("job_groups"))


@mcp.tool
async def get_job_group(ctx: Context, group_id: int) -> dict | list:
    """Get a single job group."""
    return await _request(ctx, "GET", _api(f"job_groups/{group_id}"))


@mcp.tool
async def list_job_group_jobs(ctx: Context, group_id: int) -> dict | list:
    """List jobs belonging to a job group."""
    return await _request(ctx, "GET", _api(f"job_groups/{group_id}/jobs"))


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
    return await _request(
        ctx, "GET", _api(f"job_groups/{group_id}/build_results"), params=params
    )


@mcp.tool
async def list_parent_groups(ctx: Context) -> dict | list:
    """List parent job groups."""
    return await _request(ctx, "GET", _api("parent_groups"))


@mcp.tool
async def get_parent_group(ctx: Context, group_id: int) -> dict | list:
    """Get a single parent job group."""
    return await _request(ctx, "GET", _api(f"parent_groups/{group_id}"))


@mcp.tool
async def list_assets(ctx: Context) -> dict | list:
    """List assets known to the system."""
    return await _request(ctx, "GET", _api("assets"))


@mcp.tool
async def get_asset(ctx: Context, asset_id: int) -> dict | list:
    """Get a single asset by id."""
    return await _request(ctx, "GET", _api(f"assets/{asset_id}"))


@mcp.tool
async def list_workers(ctx: Context) -> dict | list:
    """List registered worker instances."""
    return await _request(ctx, "GET", _api("workers"))


@mcp.tool
async def list_bugs(ctx: Context) -> dict | list:
    """List tracked bugs referenced by jobs."""
    return await _request(ctx, "GET", _api("bugs"))


@mcp.tool
async def search(ctx: Context, q: str) -> dict | list:
    """Full-text search across jobs, groups, and test modules."""
    return await _request(ctx, "GET", _api("experimental/search"), params={"q": q})


@mcp.tool
async def get_scheduled_product(ctx: Context, scheduled_product_id: int) -> dict | list:
    """Get a scheduled product (result of a prior ISO trigger)."""
    return await _request(ctx, "GET", _api(f"isos/{scheduled_product_id}"))


@mcp.tool
async def get_iso_job_stats(ctx: Context) -> dict | list:
    """Get job statistics for scheduled products."""
    return await _request(ctx, "GET", _api("isos/job_stats"))


@mcp.tool
async def list_group_comments(ctx: Context, group_id: int) -> dict | list:
    """List comments on a job group."""
    return await _request(ctx, "GET", _api(f"groups/{group_id}/comments"))


@mcp.tool
async def list_parent_group_comments(ctx: Context, parent_group_id: int) -> dict | list:
    """List comments on a parent job group."""
    return await _request(ctx, "GET", _api(f"parent_groups/{parent_group_id}/comments"))


# --------------------------------------------------------------------------- #
# MUTATING tools (require credentials; 403 without)                            #
# --------------------------------------------------------------------------- #


@mcp.tool(tags={MUTATING_TAG})
async def restart_jobs(ctx: Context, job_ids: list[int]) -> list:
    """Restart each of the given jobs."""
    results = []
    for job_id in job_ids:
        results.append(await _request(ctx, "POST", _api(f"jobs/{job_id}/restart")))
    return results


@mcp.tool(tags={MUTATING_TAG})
async def cancel_job(ctx: Context, job_id: int) -> dict | list:
    """Cancel a running or scheduled job."""
    return await _request(ctx, "POST", _api(f"jobs/{job_id}/cancel"))


@mcp.tool(tags={MUTATING_TAG})
async def add_job_comment(ctx: Context, job_id: int, text: str) -> dict | list:
    """Add a comment to a job."""
    return await _request(
        ctx, "POST", _api(f"jobs/{job_id}/comments"), data={"text": text}
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
    return await _request(ctx, "POST", _api("isos"), data=body)


@mcp.tool(tags={MUTATING_TAG})
async def delete_job(ctx: Context, job_id: int) -> dict | list:
    """Delete a job."""
    result = await _request(ctx, "DELETE", _api(f"jobs/{job_id}"))
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
    return await _request(ctx, "POST", _api(f"jobs/{job_id}/duplicate"), data=data)


@mcp.tool(tags={MUTATING_TAG})
async def set_job_priority(ctx: Context, job_id: int, prio: int) -> dict | list:
    """Set the priority of a job."""
    return await _request(ctx, "POST", _api(f"jobs/{job_id}/prio"), data={"prio": prio})


@mcp.tool(tags={MUTATING_TAG})
async def restart_jobs_bulk(
    ctx: Context,
    job_ids: list[int],
    force: int | None = None,
    prio: int | None = None,
) -> dict | list:
    """Restart several jobs in one bulk request."""
    data = _drop_none({"jobs": job_ids, "force": force, "prio": prio})
    return await _request(ctx, "POST", _api("jobs/restart"), data=data)


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
    return await _request(ctx, "POST", _api("jobs/cancel"), params=params)


@mcp.tool(tags={MUTATING_TAG})
async def add_group_comment(ctx: Context, group_id: int, text: str) -> dict | list:
    """Add a comment to a job group."""
    return await _request(
        ctx, "POST", _api(f"groups/{group_id}/comments"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def add_parent_group_comment(
    ctx: Context, parent_group_id: int, text: str
) -> dict | list:
    """Add a comment to a parent job group."""
    return await _request(
        ctx,
        "POST",
        _api(f"parent_groups/{parent_group_id}/comments"),
        data={"text": text},
    )


@mcp.tool(tags={MUTATING_TAG})
async def update_job_comment(
    ctx: Context, job_id: int, comment_id: int, text: str
) -> dict | list:
    """Update an existing job comment."""
    return await _request(
        ctx, "PUT", _api(f"jobs/{job_id}/comments/{comment_id}"), data={"text": text}
    )


@mcp.tool(tags={MUTATING_TAG})
async def delete_job_comment(ctx: Context, job_id: int, comment_id: int) -> dict | list:
    """Delete a job comment."""
    result = await _request(ctx, "DELETE", _api(f"jobs/{job_id}/comments/{comment_id}"))
    # A 204 No Content yields a raw httpx Response, not a dict/list; normalize.
    return result if isinstance(result, (dict, list)) else {}


@mcp.tool(tags={MUTATING_TAG})
async def create_bug(ctx: Context, bugid: str, title: str | None = None) -> dict | list:
    """Create a tracked bug reference."""
    data = _drop_none({"bugid": bugid, "title": title})
    return await _request(ctx, "POST", _api("bugs"), data=data)


@mcp.tool(tags={MUTATING_TAG})
async def cancel_scheduled_product(ctx: Context, name: str) -> dict | list:
    """Cancel a scheduled product / ISO by name."""
    return await _request(ctx, "POST", _api(f"isos/{name}/cancel"))


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
