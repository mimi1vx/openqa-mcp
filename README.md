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
| `list_jobs` | List jobs matching the given filters. |
| `list_jobs_overview` | List a condensed jobs overview matching the given filters. |
| `get_job` | Get full details for a single job. |
| `get_job_comments` | List comments on a job. |
| `list_machines` | List configured worker machines. |
| `list_test_suites` | List configured test suites. |
| `list_products` | List configured products (mediums). |
| `find_jobs_by_setting` | Find jobs whose setting `key` equals `list_value`. |

`list_jobs` and `list_jobs_overview` accept the same optional filters:
`state`, `result`, `distri`, `version`, `build`, `test`, `arch`, `machine`,
`groupid`, `group`, `latest`, `limit`, `page`, `ids`. Unset filters are
dropped from the request.

### Mutating tools (require credentials)

| Tool | Description |
| --- | --- |
| `restart_jobs` | Restart each of the given jobs. |
| `cancel_job` | Cancel a running or scheduled job. |
| `add_job_comment` | Add a comment to a job. |
| `trigger_isos` | Trigger ISO test scheduling for a product. |
| `delete_job` | Delete a job. |

Mutating tools carry the `mutating` tag so MCP clients can gate them behind
confirmation.

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

For remote or shared deployments, run over HTTP with `--http` or
`OPENQA_MCP_TRANSPORT=http`:

```sh
OPENQA_MCP_TRANSPORT=http OPENQA_MCP_HOST=127.0.0.1 OPENQA_MCP_PORT=8000 uv run openqa-mcp
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENQA_MCP_TRANSPORT` | `stdio` | Set to `http` to serve over HTTP. |
| `OPENQA_MCP_HOST` | `127.0.0.1` | HTTP bind host. |
| `OPENQA_MCP_PORT` | `8000` | HTTP bind port. |

Press `Ctrl-C` to stop; the server shuts down cleanly and closes its client.

## Development

```sh
uv run pytest        # run the test suite
uv run ruff check .  # lint
```
