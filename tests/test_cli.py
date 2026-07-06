"""Tests for the argparse CLI and transport dispatch in ``__main__``."""

import asyncio

import pytest

from openqa_mcp.__main__ import build_parser, main
from openqa_mcp.server import MUTATING_TAG, disable_mutating_tools, mcp


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate each test from ambient transport env configuration."""
    for var in (
        "OPENQA_MCP_TRANSPORT",
        "OPENQA_MCP_HOST",
        "OPENQA_MCP_PORT",
        "OPENQA_READONLY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def restore_tools():
    """Snapshot the tool registry and restore it after a test mutates it.

    ``disable_mutating_tools`` removes tools from the module-level ``mcp``
    singleton, so tests that call it must put them back to avoid leaking into
    the rest of the suite.
    """
    snapshot = asyncio.run(mcp.list_tools())
    yield
    present = {t.name for t in asyncio.run(mcp.list_tools())}
    for tool in snapshot:
        if tool.name not in present:
            mcp.local_provider.add_tool(tool)


def test_defaults():
    args = build_parser().parse_args([])
    assert args.http is False
    assert args.stdio is False
    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_server_and_port_flags():
    args = build_parser().parse_args(["--server", "0.0.0.0", "--port", "9001"])
    assert args.host == "0.0.0.0"
    assert args.port == 9001


def test_env_supplies_defaults(monkeypatch):
    monkeypatch.setenv("OPENQA_MCP_HOST", "10.0.0.1")
    monkeypatch.setenv("OPENQA_MCP_PORT", "7000")
    args = build_parser().parse_args([])
    assert args.host == "10.0.0.1"
    assert args.port == 7000


def test_http_and_stdio_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--http", "--stdio"])


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0


def _capture_run(monkeypatch):
    """Patch ``mcp.run`` to record how it was invoked instead of serving."""
    calls = {}

    def fake_run(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr("openqa_mcp.__main__.mcp.run", fake_run)
    return calls


def test_main_default_is_stdio(monkeypatch):
    calls = _capture_run(monkeypatch)
    monkeypatch.setattr("sys.argv", ["openqa-mcp"])
    main()
    assert calls["kwargs"] == {}
    assert calls["args"] == ()


def test_main_http_dispatch(monkeypatch):
    calls = _capture_run(monkeypatch)
    monkeypatch.setattr(
        "sys.argv", ["openqa-mcp", "--http", "--server", "0.0.0.0", "--port", "9001"]
    )
    main()
    assert calls["kwargs"] == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 9001,
    }


def test_main_env_selects_http(monkeypatch):
    calls = _capture_run(monkeypatch)
    monkeypatch.setenv("OPENQA_MCP_TRANSPORT", "http")
    monkeypatch.setattr("sys.argv", ["openqa-mcp"])
    main()
    assert calls["kwargs"]["transport"] == "http"


def test_main_stdio_flag_overrides_env(monkeypatch):
    calls = _capture_run(monkeypatch)
    monkeypatch.setenv("OPENQA_MCP_TRANSPORT", "http")
    monkeypatch.setattr("sys.argv", ["openqa-mcp", "--stdio"])
    main()
    assert calls["kwargs"] == {}


def test_readonly_defaults_false():
    assert build_parser().parse_args([]).readonly is False


def test_readonly_flag_sets_true():
    assert build_parser().parse_args(["--readonly"]).readonly is True


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_readonly_env_truthy(monkeypatch, value):
    monkeypatch.setenv("OPENQA_READONLY", value)
    assert build_parser().parse_args([]).readonly is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
def test_readonly_env_falsy(monkeypatch, value):
    monkeypatch.setenv("OPENQA_READONLY", value)
    assert build_parser().parse_args([]).readonly is False


def test_disable_mutating_tools_removes_tagged(restore_tools):
    removed = disable_mutating_tools()
    assert set(removed) == {
        "restart_jobs",
        "cancel_job",
        "add_job_comment",
        "trigger_isos",
        "delete_job",
    }
    remaining = asyncio.run(mcp.list_tools())
    assert not any(MUTATING_TAG in t.tags for t in remaining)


def test_main_readonly_disables_tools(monkeypatch, restore_tools):
    _capture_run(monkeypatch)
    monkeypatch.setattr("sys.argv", ["openqa-mcp", "--readonly"])
    main()
    remaining = asyncio.run(mcp.list_tools())
    assert not any(MUTATING_TAG in t.tags for t in remaining)
