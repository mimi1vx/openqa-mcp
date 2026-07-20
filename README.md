# openqa-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes curated,
typed tools over the [openQA](https://open.qa) REST API. It is built on
[fastmcp](https://github.com/jlowin/fastmcp) 3.x and the
[openqa-async](https://pypi.org/project/openqa-async/) transport client.

Read tools work anonymously; mutating tools require API credentials and
return `403` without them.

## Install

```sh
uv sync
```

This installs the package and its dependencies into a project virtualenv
and exposes the `openqa-mcp` console script.

## Configuration

The server reads its configuration from environment variables, falling back
to the openQA client config file for credentials.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENQA_SERVER` | openqa-async default | openQA host (e.g. `openqa.opensuse.org`). |
| `OPENQA_API_KEY` | *(unset)* | API key; overrides the config file when set. |
| `OPENQA_API_SECRET` | *(unset)* | API secret; overrides the config file when set. |
| `OPENQA_VERIFY` | `true` | TLS verification: `true`/`false`, or a path to a CA bundle. |

`OPENQA_API_KEY` and `OPENQA_API_SECRET` only take effect when **both** are
set; a partial pair is ignored so the client is never half-configured.

### Config file

If the env credentials are not set, openqa-async loads them from
`~/.config/openqa/client.conf` (or `/etc/openqa/client.conf`). Generate a
key/secret from the *API keys* page of your openQA instance and add a section
keyed by the host:

```ini
[openqa.opensuse.org]
key = YOUR_API_KEY
secret = YOUR_API_SECRET
```

Without any credentials the server is GET-only (read tools succeed, mutating
tools get `403`).

## Tools

### Read tools

| Tool | Description |
| --- | --- |
| `list_jobs` | List jobs matching the given filters. Pass `summary=True` for a compact triage breakdown. |
| `list_jobs_overview` | List a condensed jobs overview matching the given filters. Pass `summary=True` for a compact triage breakdown. |
| `get_job` | Get full details for a single job. |
| `get_job_comments` | List comments on a job. |
| `list_machines` | List configured worker machines. |
| `list_test_suites` | List configured test suites. |
| `list_products` | List configured products (mediums). |
| `find_jobs_by_setting` | Find jobs whose setting `key` equals `list_value`. |
| `get_job_details` | Get a single job with full test-module/step details. |
| `get_job_status` | Get a lightweight job status (id, state, result, blocked_by_id). |
| `list_job_groups` | List job groups. |
| `get_job_group` | Get a single job group. |
| `list_job_group_jobs` | List jobs belonging to a job group. |
| `get_job_group_build_results` | Get aggregated build results for a job group. |
| `list_parent_groups` | List parent job groups. |
| `get_parent_group` | Get a single parent job group. |
| `list_assets` | List assets known to the system. |
| `get_asset` | Get a single asset by id. |
| `list_workers` | List registered worker instances. |
| `list_bugs` | List tracked bugs referenced by jobs. |
| `search` | Full-text search across jobs, groups, and test modules. |
| `get_scheduled_product` | Get a scheduled product (result of a prior ISO trigger). |
| `get_iso_job_stats` | Get job statistics for scheduled products. |
| `list_group_comments` | List comments on a job group. |
| `list_parent_group_comments` | List comments on a parent job group. |

`list_jobs` and `list_jobs_overview` accept the same optional filters:
`state`, `result`, `distri`, `version`, `build`, `test`, `arch`, `machine`,
`groupid`, `group`, `latest`, `limit`, `page`, `ids`. Unset filters are
dropped from the request.

Both also accept `summary` (default `False`). The default full result can be
very large (~1.5 MB / 150+ jobs for a populated build) and may be truncated by
MCP clients. Pass `summary=True` for a compact per-result breakdown:

```json
{
  "total": 156,
  "by_result": {"passed": 57, "softfailed": 61, "failed": 7, "...": 0},
  "by_state":  {"done": 136, "cancelled": 20},
  "by_arch":   {"x86_64": 78, "aarch64": 39, "s390x": 39},
  "jobs": {"failed": [{"id": 1, "test": "install", "arch": "x86_64"}], "...": []}
}
```

Jobs bucket by `result`; in-progress jobs (result `none`) bucket by `state`
(e.g. `running`, `scheduled`). To work with the full data instead, save it to a
temporary file and process it with `jq`, e.g.
`jq '.jobs[] | select(.result=="failed")'`.

### Mutating tools (require credentials)

| Tool | Description |
| --- | --- |
| `restart_jobs` | Restart each of the given jobs. |
| `cancel_job` | Cancel a running or scheduled job. |
| `add_job_comment` | Add a comment to a job. |
| `trigger_isos` | Trigger ISO test scheduling for a product. |
| `delete_job` | Delete a job. |
| `duplicate_job` | Duplicate (clone) a job. |
| `set_job_priority` | Set the priority of a job. |
| `restart_jobs_bulk` | Restart several jobs in one bulk request. |
| `cancel_jobs` | Cancel all jobs matching the given filters. |
| `add_group_comment` | Add a comment to a job group. |
| `add_parent_group_comment` | Add a comment to a parent job group. |
| `update_job_comment` | Update an existing job comment. |
| `delete_job_comment` | Delete a job comment. |
| `create_bug` | Create a tracked bug reference. |
| `cancel_scheduled_product` | Cancel a scheduled product / ISO by name. |

Mutating tools carry the `mutating` tag so MCP clients can gate them behind
confirmation. To drop them entirely, start the server in read-only mode with
`--readonly` (or `OPENQA_READONLY=true`): the mutating tools are never
registered, so clients see only the read tools.

## Running

### stdio (default)

Most local MCP clients spawn the server over stdio. Wire it in with:

```sh
uv run openqa-mcp
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "openqa": {
      "command": "uv",
      "args": ["run", "openqa-mcp"],
      "env": {
        "OPENQA_SERVER": "openqa.opensuse.org"
      }
    }
  }
}
```

### HTTP (optional)

For remote or shared deployments, run over HTTP with `--http`:

```sh
uv run openqa-mcp --http --server 127.0.0.1 --port 8000
```

The server can also be launched as a module:

```sh
uv run python -m openqa_mcp --http --port 8000
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--http` | off | Serve over HTTP instead of stdio. |
| `--stdio` | on | Serve over stdio; overrides `OPENQA_MCP_TRANSPORT=http`. |
| `--server` | `127.0.0.1` | HTTP bind host. |
| `--port` | `8000` | HTTP bind port. |
| `--readonly` | off | Unregister all mutating tools (read-only server). |

Flags override the environment, which supplies the defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENQA_MCP_TRANSPORT` | `stdio` | Set to `http` to serve over HTTP. |
| `OPENQA_MCP_HOST` | `127.0.0.1` | Default HTTP bind host. |
| `OPENQA_MCP_PORT` | `8000` | Default HTTP bind port. |
| `OPENQA_READONLY` | `false` | Set truthy (`1`/`true`/`yes`/`on`) to disable mutating tools. |
| `OPENQA_MCP_HEARTBEAT_INTERVAL` | `15.0` | Seconds between progress "heartbeat" pings sent while a tool waits on a slow openQA call, so MCP clients see liveness instead of timing out. Set `<=0` to disable. Pings are a no-op unless the client sent a `progressToken`. |

Press `Ctrl-C` to stop; the server shuts down cleanly and closes its client.

## Development

```sh
uv run pytest        # run the test suite
uv run ruff check .  # lint
```
