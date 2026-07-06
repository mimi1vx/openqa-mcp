"""Smoke tests for the curated MCP tools.

Each test drives a tool end-to-end through the FastMCP in-memory client and
intercepts the outgoing HTTP with respx, so no live openQA is required. The
server's lifespan builds the shared client from the environment, so env-based
configuration is exercised the same way it would be in production.

Note: this openqa-async version joins paths directly onto the server host, so
the tools supply the ``/api/v1`` prefix themselves; the expected paths are
``/api/v1/jobs`` etc.
"""

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
