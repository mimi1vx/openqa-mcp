"""Command-line entry point for the openQA MCP server.

Selects the transport and, for HTTP, the bind address. Flags override the
environment; the environment (``OPENQA_MCP_TRANSPORT``/``HOST``/``PORT``)
supplies the defaults. Run with ``openqa-mcp`` or ``python -m openqa_mcp``.
"""

from __future__ import annotations

import argparse
import os

from .server import disable_mutating_tools, mcp


def _env_flag(name: str) -> bool:
    """Interpret an environment variable as a boolean toggle.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``.
    Anything else (including unset) is false.
    """
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    ``--http``/``--stdio`` are mutually exclusive; neither (nor
    ``OPENQA_MCP_TRANSPORT=http``) means stdio. ``--server``/``--port`` set the
    HTTP bind address, defaulting from ``OPENQA_MCP_HOST``/``OPENQA_MCP_PORT``.
    """
    parser = argparse.ArgumentParser(
        prog="openqa-mcp",
        description="Run the openQA MCP server over stdio (default) or HTTP.",
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--http",
        action="store_true",
        help="serve over HTTP instead of stdio",
    )
    transport.add_argument(
        "--stdio",
        action="store_true",
        help="serve over stdio (default; overrides OPENQA_MCP_TRANSPORT=http)",
    )
    parser.add_argument(
        "--server",
        dest="host",
        default=os.environ.get("OPENQA_MCP_HOST", "127.0.0.1"),
        help="HTTP bind host (default: %(default)s, or OPENQA_MCP_HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPENQA_MCP_PORT", "8000")),
        help="HTTP bind port (default: %(default)s, or OPENQA_MCP_PORT)",
    )
    parser.add_argument(
        "--readonly",
        action="store_true",
        default=_env_flag("OPENQA_READONLY"),
        help="disable all mutating tools (default: OPENQA_READONLY)",
    )
    return parser


def main() -> None:
    """Parse arguments and run the server on the selected transport."""
    args = build_parser().parse_args()

    if args.readonly:
        disable_mutating_tools()

    # An explicit --stdio wins; otherwise --http or the env toggle selects HTTP.
    http = not args.stdio and (
        args.http or os.environ.get("OPENQA_MCP_TRANSPORT") == "http"
    )
    try:
        if http:
            mcp.run(transport="http", host=args.host, port=args.port)
        else:
            mcp.run()
    except KeyboardInterrupt:
        # Ctrl-C: the lifespan's finally block already closed the client as the
        # async context unwound; swallow the traceback and exit cleanly.
        pass


if __name__ == "__main__":
    main()
