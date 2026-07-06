"""Tests for the argparse CLI and transport dispatch in ``__main__``."""

import pytest

from openqa_mcp.__main__ import build_parser, main


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate each test from ambient transport env configuration."""
    for var in ("OPENQA_MCP_TRANSPORT", "OPENQA_MCP_HOST", "OPENQA_MCP_PORT"):
        monkeypatch.delenv(var, raising=False)


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
