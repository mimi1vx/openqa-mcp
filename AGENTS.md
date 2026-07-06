# AGENTS.md

MCP server exposing curated, typed tools over the openQA REST API. Built on
`fastmcp` 3.x + the `openqa-async` transport client. See `README.md` for user
docs (install, env config, running); this file covers what's non-obvious when
editing the code.

## Commands

Toolchain is `uv` + `ruff` + `ty` (all pinned in the dev group). Run in order:

```sh
uv run ruff check .          # lint
uv run ty check              # type-check
uv run pytest                # tests
uv run pytest tests/test_cli.py::test_defaults   # single test
```

`ruff` and `ty` are dev deps, not in README's Development section — use them.
Requires Python 3.13+.

## Layout

- `server.py` — the `mcp` instance + all tool definitions. No entry point.
- `__main__.py` — the argparse CLI + `main()`. Entry point is
  `openqa_mcp.__main__:main`; also runnable as `python -m openqa_mcp`. Keep
  `main`/CLI here, not in `server.py`.
- `client.py` — `get_client()` (env config) and `lifespan` (shared client).

## Gotchas

- **openqa-async private-attribute touch-point:** `_apply_env_credentials` in
  `client.py` reaches into `client._apikey` / `.apisecret` and *rebuilds*
  `client.client` because auth is baked in at construction — assigning creds
  alone is a no-op. Keep this the ONLY place touching those privates.
- **Credentials need both `OPENQA_API_KEY` and `OPENQA_API_SECRET`;** a partial
  pair is ignored on purpose. Without creds the server is GET-only (mutating
  tools return 403). Tests must `monkeypatch.delenv` these to stay deterministic.
- **Test URL paths have no `/api/v1` prefix** — this openqa-async version joins
  paths straight onto the host, so respx routes/assertions use `/jobs`, not
  `/api/v1/jobs`.
- **Tests hit no live openQA:** `test_tools.py` drives tools through the FastMCP
  in-memory client and intercepts HTTP with `respx`.
- **CLI transport precedence:** explicit `--stdio` beats `OPENQA_MCP_TRANSPORT=http`;
  flags override env, env supplies argparse defaults. `--server` = HTTP bind host
  (not the openQA target, which is `OPENQA_SERVER`).
- **`fastmcp` types `ctx.lifespan_context` generically** — `_client` casts to
  `AppContext` so `.client` type-checks. Preserve the cast.

## Conventions

- Read tools are anonymous; mutating tools are tagged `{"mutating"}` and grouped
  under a comment banner in `server.py`. Follow the pattern: thin typed wrapper
  over `openqa_request`, one-line docstring (becomes the tool description),
  `_drop_none` on optional params.
- Conventional Commits; commit only when asked.
