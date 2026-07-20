"""Smoke tests for the curated MCP tools.

Each test drives a tool end-to-end through the FastMCP in-memory client and
intercepts the outgoing HTTP with respx, so no live openQA is required. The
server's lifespan builds the shared client from the environment, so env-based
configuration is exercised the same way it would be in production.

Note: this openqa-async version joins paths directly onto the server host, so
the tools supply the ``/api/v1`` prefix themselves; the expected paths are
``/api/v1/jobs`` etc.
"""

import asyncio

import httpx
import pytest
import respx

from fastmcp import Client

from openqa_mcp.server import mcp

_SERVER = "https://openqa.example.com"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Pin the server and strip ambient creds so tests are deterministic."""
    for var in ("OPENQA_VERIFY", "OPENQA_API_KEY", "OPENQA_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENQA_SERVER", "openqa.example.com")


async def test_list_jobs_builds_get_with_params_and_returns_json():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": [{"id": 42}]})
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "list_jobs", {"state": "done", "arch": "x86_64"}
            )

    assert route.called
    request = route.calls.last.request
    assert request.method == "GET"
    assert request.url.path == "/api/v1/jobs"
    assert dict(request.url.params) == {"state": "done", "arch": "x86_64"}
    assert result.structured_content == {"result": {"jobs": [{"id": 42}]}}


async def test_none_params_are_dropped_from_query_string():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": []})
        )
        async with Client(mcp) as client:
            # Only `state` is set; every other param stays None and must not appear.
            await client.call_tool("list_jobs", {"state": "running"})

    params = dict(route.calls.last.request.url.params)
    assert params == {"state": "running"}
    assert "result" not in params
    assert "arch" not in params


async def test_list_jobs_paginates_with_offset_not_page():
    # openQA's job#list reads `offset`; it silently ignores `page`. The tool must
    # forward the real, effective pagination parameter.
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": []})
        )
        async with Client(mcp) as client:
            await client.call_tool("list_jobs", {"offset": 100})

    params = dict(route.calls.last.request.url.params)
    assert params == {"offset": "100"}


async def test_list_jobs_rejects_nonexistent_page_param():
    # `page` was never honored by openQA; it must no longer be a tool parameter.
    async with Client(mcp) as client:
        with pytest.raises(Exception):
            await client.call_tool("list_jobs", {"page": 2})


_SUMMARY_JOBS = {
    "jobs": [
        {
            "id": 1,
            "test": "boot",
            "result": "passed",
            "state": "done",
            "settings": {"ARCH": "x86_64"},
        },
        {
            "id": 2,
            "test": "kdump",
            "result": "softfailed",
            "state": "done",
            "settings": {"ARCH": "aarch64"},
        },
        {
            "id": 3,
            "test": "install",
            "result": "failed",
            "state": "done",
            "settings": {"ARCH": "x86_64"},
        },
        {
            "id": 4,
            "test": "skipped_one",
            "result": "skipped",
            "state": "cancelled",
            "settings": {"ARCH": "s390x"},
        },
        # In-progress: result="none" -> bucket by state.
        {
            "id": 5,
            "test": "wip",
            "result": "none",
            "state": "running",
            "settings": {"ARCH": "x86_64"},
        },
        # Missing settings must not raise; arch is None.
        {"id": 6, "test": "nosettings", "result": "passed", "state": "done"},
    ]
}


async def test_list_jobs_summary_returns_compact_shape():
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{_SERVER}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=_SUMMARY_JOBS)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "list_jobs", {"distri": "sle-micro", "summary": True}
            )

    summary = result.structured_content["result"]
    assert summary["total"] == 6
    assert summary["by_result"] == {
        "passed": 2,
        "softfailed": 1,
        "failed": 1,
        "skipped": 1,
        "none": 1,
    }
    assert summary["by_state"] == {"done": 4, "cancelled": 1, "running": 1}
    assert summary["by_arch"] == {"x86_64": 3, "aarch64": 1, "s390x": 1}
    # Softfailed + skipped surfaced; in-progress job buckets under its state.
    assert [j["id"] for j in summary["jobs"]["passed"]] == [1, 6]
    assert summary["jobs"]["softfailed"][0]["test"] == "kdump"
    assert summary["jobs"]["skipped"][0]["arch"] == "s390x"
    assert summary["jobs"]["running"][0]["id"] == 5
    assert "none" not in summary["jobs"]
    # Job lacking settings yields arch=None without raising.
    assert summary["jobs"]["passed"][1]["arch"] is None


async def test_list_jobs_overview_summary_uses_shared_helper():
    # Overview endpoint returns a bare list of jobs.
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{_SERVER}/api/v1/jobs/overview").mock(
            return_value=httpx.Response(200, json=_SUMMARY_JOBS["jobs"])
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "list_jobs_overview", {"distri": "sle-micro", "summary": True}
            )

    summary = result.structured_content["result"]
    assert summary["total"] == 6
    assert summary["by_result"]["softfailed"] == 1
    assert summary["jobs"]["running"][0]["id"] == 5


async def test_summary_tool_descriptions_warn_about_size():
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("list_jobs", "list_jobs_overview"):
        desc = tools[name].description or ""
        assert "WARNING" in desc
        assert "jq" in desc
        assert "summary=True" in desc


async def test_mutating_tool_issues_correct_post():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/jobs/7/comments").mock(
            return_value=httpx.Response(200, json={"id": 100})
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "add_job_comment", {"job_id": 7, "text": "looks flaky"}
            )

    request = route.calls.last.request
    assert request.method == "POST"
    assert request.url.path == "/api/v1/jobs/7/comments"
    # Body is form-encoded (Mojolicious API), not JSON.
    assert b"text=looks+flaky" in request.content
    assert result.structured_content == {"result": {"id": 100}}


async def test_env_credentials_set_api_key_header(monkeypatch):
    monkeypatch.setenv("OPENQA_API_KEY", "DEADBEEF")
    monkeypatch.setenv("OPENQA_API_SECRET", "C0FFEE")

    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": []})
        )
        async with Client(mcp) as client:
            await client.call_tool("list_jobs", {})

    assert route.calls.last.request.headers.get("X-API-Key") == "DEADBEEF"


# --------------------------------------------------------------------------- #
# Tier 1 read tools                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("tool", "args", "method", "path"),
    [
        ("get_job_details", {"job_id": 5}, "GET", "/api/v1/jobs/5/details"),
        (
            "get_job_status",
            {"job_id": 5},
            "GET",
            "/api/v1/experimental/jobs/5/status",
        ),
        ("list_job_groups", {}, "GET", "/api/v1/job_groups"),
        ("get_job_group", {"group_id": 3}, "GET", "/api/v1/job_groups/3"),
        (
            "list_job_group_jobs",
            {"group_id": 3},
            "GET",
            "/api/v1/job_groups/3/jobs",
        ),
        (
            "get_job_group_build_results",
            {"group_id": 3},
            "GET",
            "/api/v1/job_groups/3/build_results",
        ),
        ("list_parent_groups", {}, "GET", "/api/v1/parent_groups"),
        ("get_parent_group", {"group_id": 8}, "GET", "/api/v1/parent_groups/8"),
        ("list_assets", {}, "GET", "/api/v1/assets"),
        ("get_asset", {"asset_id": 12}, "GET", "/api/v1/assets/12"),
        ("list_workers", {}, "GET", "/api/v1/workers"),
        ("list_bugs", {}, "GET", "/api/v1/bugs"),
        (
            "get_scheduled_product",
            {"scheduled_product_id": 9},
            "GET",
            "/api/v1/isos/9",
        ),
        ("get_iso_job_stats", {}, "GET", "/api/v1/isos/job_stats"),
        (
            "list_group_comments",
            {"group_id": 3},
            "GET",
            "/api/v1/groups/3/comments",
        ),
        (
            "list_parent_group_comments",
            {"parent_group_id": 8},
            "GET",
            "/api/v1/parent_groups/8/comments",
        ),
    ],
)
async def test_read_tool_hits_expected_endpoint(tool, args, method, path):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, f"{_SERVER}{path}").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with Client(mcp) as client:
            result = await client.call_tool(tool, args)

    request = route.calls.last.request
    assert request.method == method
    assert request.url.path == path
    assert result.structured_content == {"result": {"ok": True}}


async def test_get_job_status_passes_follow_param():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/experimental/jobs/5/status").mock(
            return_value=httpx.Response(200, json={"id": 5, "state": "done"})
        )
        async with Client(mcp) as client:
            await client.call_tool("get_job_status", {"job_id": 5, "follow": 1})

    assert dict(route.calls.last.request.url.params) == {"follow": "1"}


async def test_build_results_drops_none_and_passes_set_params():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/job_groups/3/build_results").mock(
            return_value=httpx.Response(200, json={})
        )
        async with Client(mcp) as client:
            await client.call_tool(
                "get_job_group_build_results",
                {"group_id": 3, "limit_builds": 5},
            )

    assert dict(route.calls.last.request.url.params) == {"limit_builds": "5"}


async def test_search_requires_and_sends_q():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(f"{_SERVER}/api/v1/experimental/search").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        async with Client(mcp) as client:
            await client.call_tool("search", {"q": "flaky"})

    assert dict(route.calls.last.request.url.params) == {"q": "flaky"}


# --------------------------------------------------------------------------- #
# Tier 2 mutating tools                                                        #
# --------------------------------------------------------------------------- #


async def test_duplicate_job_posts_with_optional_body():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/jobs/5/duplicate").mock(
            return_value=httpx.Response(200, json={"id": 99})
        )
        async with Client(mcp) as client:
            result = await client.call_tool("duplicate_job", {"job_id": 5, "prio": 40})

    request = route.calls.last.request
    assert request.method == "POST"
    assert request.url.path == "/api/v1/jobs/5/duplicate"
    assert b"prio=40" in request.content
    assert result.structured_content == {"result": {"id": 99}}


async def test_set_job_priority_posts_prio():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/jobs/5/prio").mock(
            return_value=httpx.Response(200, json={"result": True})
        )
        async with Client(mcp) as client:
            await client.call_tool("set_job_priority", {"job_id": 5, "prio": 70})

    assert b"prio=70" in route.calls.last.request.content


async def test_restart_jobs_bulk_repeats_jobs_in_body():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/jobs/restart").mock(
            return_value=httpx.Response(200, json={"result": []})
        )
        async with Client(mcp) as client:
            await client.call_tool("restart_jobs_bulk", {"job_ids": [1, 2]})

    content = route.calls.last.request.content
    assert b"jobs=1" in content
    assert b"jobs=2" in content


async def test_cancel_jobs_sends_filters_as_query_params():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/jobs/cancel").mock(
            return_value=httpx.Response(200, json={"result": 3})
        )
        async with Client(mcp) as client:
            await client.call_tool("cancel_jobs", {"state": "scheduled"})

    request = route.calls.last.request
    assert request.method == "POST"
    assert dict(request.url.params) == {"state": "scheduled"}


@pytest.mark.parametrize(
    ("tool", "args", "path"),
    [
        (
            "add_group_comment",
            {"group_id": 3, "text": "note"},
            "/api/v1/groups/3/comments",
        ),
        (
            "add_parent_group_comment",
            {"parent_group_id": 8, "text": "note"},
            "/api/v1/parent_groups/8/comments",
        ),
    ],
)
async def test_group_comment_posts_text(tool, args, path):
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}{path}").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        async with Client(mcp) as client:
            await client.call_tool(tool, args)

    request = route.calls.last.request
    assert request.url.path == path
    assert b"text=note" in request.content


async def test_update_job_comment_issues_put():
    with respx.mock(assert_all_called=True) as router:
        route = router.put(f"{_SERVER}/api/v1/jobs/7/comments/2").mock(
            return_value=httpx.Response(200, json={"id": 2})
        )
        async with Client(mcp) as client:
            await client.call_tool(
                "update_job_comment",
                {"job_id": 7, "comment_id": 2, "text": "edited"},
            )

    request = route.calls.last.request
    assert request.method == "PUT"
    assert request.url.path == "/api/v1/jobs/7/comments/2"
    assert b"text=edited" in request.content


async def test_delete_job_comment_normalizes_204():
    with respx.mock(assert_all_called=True) as router:
        route = router.delete(f"{_SERVER}/api/v1/jobs/7/comments/2").mock(
            return_value=httpx.Response(204)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "delete_job_comment", {"job_id": 7, "comment_id": 2}
            )

    assert route.calls.last.request.method == "DELETE"
    assert result.structured_content == {"result": {}}


async def test_create_bug_posts_bugid():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/bugs").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        async with Client(mcp) as client:
            await client.call_tool("create_bug", {"bugid": "bsc#1234"})

    assert b"bugid=bsc%231234" in route.calls.last.request.content


async def test_cancel_scheduled_product_posts_by_name():
    with respx.mock(assert_all_called=True) as router:
        route = router.post(f"{_SERVER}/api/v1/isos/openSUSE.iso/cancel").mock(
            return_value=httpx.Response(200, json={"result": 1})
        )
        async with Client(mcp) as client:
            await client.call_tool("cancel_scheduled_product", {"name": "openSUSE.iso"})

    assert route.calls.last.request.method == "POST"


# --------------------------------------------------------------------------- #
# Heartbeat (progress notifications during slow calls)                         #
# --------------------------------------------------------------------------- #


async def _slow_ok(_request):
    """A respx side effect that stalls, forcing at least one heartbeat tick."""
    await asyncio.sleep(0.15)
    return httpx.Response(200, json={"jobs": []})


async def test_slow_call_emits_progress(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_HEARTBEAT_INTERVAL", "0.02")
    pings: list[tuple[float, float | None, str | None]] = []

    async def handler(progress, total, message):
        pings.append((progress, total, message))

    with respx.mock(assert_all_called=True) as router:
        router.get(f"{_SERVER}/api/v1/jobs").mock(side_effect=_slow_ok)
        async with Client(mcp) as client:
            await client.call_tool("list_jobs", {}, progress_handler=handler)

    assert pings, "expected at least one heartbeat progress notification"
    # Indeterminate progress: rising counter, no total.
    assert pings[0][1] is None
    assert pings[0][0] > 0


async def test_disabled_heartbeat_emits_no_progress(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_HEARTBEAT_INTERVAL", "0")
    pings: list[tuple[float, float | None, str | None]] = []

    async def handler(progress, total, message):
        pings.append((progress, total, message))

    with respx.mock(assert_all_called=True) as router:
        router.get(f"{_SERVER}/api/v1/jobs").mock(side_effect=_slow_ok)
        async with Client(mcp) as client:
            await client.call_tool("list_jobs", {}, progress_handler=handler)

    assert pings == []
