# log-mcp

[English](README.md) | [简体中文](README_ZH.md)

A general-purpose log query MCP Server that gives AI agents real-time querying, aggregation and cross-source correlation over your structured logs.

Built on the DuckDB SQL engine — reads JSONL / plain-text log files directly, no external database required, works with logs produced by any language or framework.

## Why log-mcp

When AI agents (like Claude Code) help you develop, test, or debug, they keep asking the same questions:

- **"Did the code I just changed throw any errors?"** — needs server logs filtered by time and level
- **"Why did this test request fail?"** — needs to follow a single call chain by `correlation_id` / `trace_id`
- **"What's the error rate over the last 5 minutes?"** — needs aggregations and percentiles
- **"What's the full path from the client click to the server response?"** — needs to correlate multiple log sources

The traditional answer is to pipe `grep` / `awk` together or have the user paste log snippets manually — slow and error-prone. log-mcp exposes structured query capability over MCP so the agent can hit logs with parameterized SQL instead.

## Features

- **Language / framework agnostic**: any service that writes JSONL or plain-text logs (Python / Go / Node / Java / Rust ...) plugs in
- **DuckDB SQL engine**: filtering, sorting, aggregation, and joins all happen inside the engine — millions of rows are fine
- **Parameterized queries**: every user input is bound through `$N` placeholders, no SQL injection
- **Cross-source field normalization**: `field_map` translates per-service field names to unified `_timestamp` / `_level` / `_message` / `_source`
- **Rotation-aware**: auto-discovers numeric (`.1/.2/.3`), date (`.YYYY-MM-DD`) and `none` rotation history files
- **Dynamic registration**: add or remove sources at runtime, with optional persistence to the config file
- **Cross-source timelines**: `UNION ALL` across sources joined by `correlation_id` etc., sorted by `_timestamp` to rebuild a call chain
- **Structured error responses**: every failure path returns a 4-part `{error_code, detail, suggestion, hints}` object so the agent can recover programmatically
- **Token-aware output**: `query` / `tail` / `cross_query` truncate any single field over 4 KB to a `<truncated:size>` placeholder by default, with an optional `fields` whitelist for tighter control
- **Zero ops overhead**: stdio transport, runs in-memory, doesn't bind any extra port

## The 7 MCP Tools

| Tool | What it does |
|------|--------------|
| `list_sources` | List registered log sources and their file status |
| `query` | Main query path: level / regex / arbitrary fields / time range, with `offset` paging and a `fields` whitelist |
| `tail` | Reverse-read the latest N rows; precise count regardless of filter hit rate; supports `fields` whitelist |
| `summary` | Aggregations: total / level_counts / top_messages / groups, plus percentiles (p50/p95/p99) and time buckets (1m/5m/1h) |
| `cross_query` | Cross-source timeline reconstruction: pin a call chain with `join_field` + `join_value`, `UNION ALL` across sources sorted by `_timestamp` |
| `register_source` | Register a new source dynamically, optionally persist to `sources.yaml` |
| `unregister_source` | Unregister a source |

## Quick Start

### 1. Install

Requires Python 3.11+. Dependencies are pulled automatically: `mcp` / `duckdb` / `pyyaml`.

**Recommended: `uv tool install` (isolated global env, no venv juggling)**

```bash
# From source (after cloning)
git clone <repo-url> log-mcp
cd log-mcp
uv tool install .

# Or straight from git
uv tool install git+<repo-url>

# Upgrade
uv tool upgrade log-mcp

# Uninstall
uv tool uninstall log-mcp
```

After install, the `log-mcp` command is on your PATH at `~/.local/bin/log-mcp` (uv adds it automatically).

**Alternative: pip editable install**

```bash
git clone <repo-url> log-mcp
cd log-mcp
pip install -e .
```

### 2. Prepare your logs

Confirm the service writes logs to a **file**, in one of these formats:

- **JSONL (recommended)**: one JSON object per line with flat fields — the default output of structlog / zerolog / pino / zap, etc.
- **Plain text**: one record per line; set `format: text` in `sources.yaml`

Note the **absolute path** of the file, plus the field names representing timestamp, level and message (you'll need them next).

### 3. Configure `sources.yaml` (optional)

See [Config format](#config-format-sourcesyaml) below. If you prefer "pure dynamic registration", skip this step and have the agent call `register_source` after startup.

### 4. Start the server

```bash
# With a config file
log-mcp --config /absolute/path/to/sources.yaml

# Pure dynamic mode (sources added at runtime via register_source)
log-mcp

# Equivalent during development (or when the entry point isn't installed)
python -m log_mcp --config /absolute/path/to/sources.yaml
```

### 5. Hook it into Claude Code

In your project's `.claude/settings.local.json`, add the MCP server and the permission allowlist. Add **all 7 tools** to `permissions.allow` so calls don't pop up an authorization dialog every time:

```json
{
  "mcpServers": {
    "log": {
      "command": "log-mcp",
      "args": ["--config", "/absolute/path/to/sources.yaml"]
    }
  },
  "permissions": {
    "allow": [
      "mcp__log__list_sources",
      "mcp__log__query",
      "mcp__log__tail",
      "mcp__log__summary",
      "mcp__log__cross_query",
      "mcp__log__register_source",
      "mcp__log__unregister_source"
    ]
  }
}
```

> If `log-mcp` isn't on PATH (e.g. you didn't use uv tool install), use an absolute path `"command": "/path/to/.venv/bin/log-mcp"` or fall back to `"command": "python", "args": ["-m", "log_mcp", "--config", "..."]`.

Restart Claude Code; `/mcp` should show the `log` server connected.

### 6. Use it

Just talk to the agent in natural language — it picks the right tool:

- "Any errors in the last 5 minutes?" → `summary` + `query`
- "Show me the latest 20 lines from api-server" → `tail`
- "The full call chain for test run-abc-123" → `query` with `correlation_id`
- "End-to-end path from client click to server response" → `cross_query`

You can also ask for tools explicitly: `list_sources` to see registered sources, `register_source` to add one.

## Config format `sources.yaml`

> **Important**: `field_map` must match the **actual field names in your log file exactly**. If the file has `timestamp`, you can't write `ts` — DuckDB will throw `BinderException`. When in doubt, `head -n 1` a real log line first.

```yaml
sources:
  # Example 1: Python structlog JSONL output
  api-server:
    description: "Backend API request log"
    path: "/var/log/api/request.jsonl"
    rotation: numeric          # numeric | date | none
    format: jsonl              # jsonl | text
    field_map:
      timestamp: ts            # source field → standard field
      level: level
      message: event

  # Example 2: Go zerolog output, rotated by date
  worker:
    description: "Background task execution log"
    path: "/var/log/worker/worker.log"
    rotation: date
    format: jsonl
    field_map:
      timestamp: time
      level: severity
      message: msg

  # Example 3: Test runner log
  test-runner:
    description: "Integration test run log"
    path: "/tmp/test-run.jsonl"
    rotation: none
    format: jsonl
    # field_map omitted → defaults to timestamp/level/message

  # Example 4: Plain-text access log from a traditional app server
  nginx:
    description: "Nginx access log"
    path: "/var/log/nginx/access.log"
    rotation: date
    format: text
```

### Standard fields (after normalization)

The query layer always operates on these fields; `field_map` translates from raw source names:

| Standard field | Meaning | Default raw field |
|----------------|---------|-------------------|
| `_timestamp` | Event time (ISO 8601 or any parseable time string) | `timestamp` |
| `_level` | Log level (error / warning / info / debug) | `level` |
| `_message` | Event description | `message` |
| `_source` | Source name (injected by MCP) | — |

All raw fields are passed through; the agent can filter by any of them via `field_filters`.

### Field filter syntax

`field_filters` (in `query` and `summary`) supports five operators:

```json
{
  "user_id": "42",                    // exact match
  "status": ">=400",                  // numeric comparison (>= <= > <)
  "path": "~^/api/v1",                // regex match (~ prefix)
  "env": "!production",               // negation (! prefix)
  "correlation_id": "run-abc-123"     // exact match
}
```

### Time expressions

`since` / `until` accept two formats:

- ISO 8601: `2026-04-15T10:00:00Z`
- Relative: `30s` / `5m` / `1h` / `1d`

## Typical workflows

### Scenario 1: Pinpoint why a test failed

```
1. Agent runs the integration test, gets a 500
2. tail(source="api-server", count=10, level="error")
   → sees the latest error: auth_failed
3. query(source="api-server", field_filters={"correlation_id": "run-001"})
   → fetches the full request chain for that test, finds the root cause
4. Agent fixes the code and re-runs
```

### Scenario 2: Watch error rate after a code change

```
1. Agent commits a change and triggers CI
2. summary(source="api-server", since="5m",
           percentile_fields=["duration_ms"],
           bucket_interval="1m")
   → recent 5-min error counts, p50/p95/p99 latency, per-minute buckets
3. If errors > 0 or p95 spikes, drop back to query for specifics
```

### Scenario 3: Cross-tier trace replay

```
cross_query(
  sources=["api-server", "test-runner"],
  join_field="correlation_id",
  join_value="run-abc-123",
  since="10m"
)
→ matching rows from each source are merged via UNION ALL,
  sorted by _timestamp into a single timeline; every row carries
  _source identifying its origin; row count = sum of per-source matches
  (no Cartesian product)
```

`since` defaults to `1h` to avoid unbounded scans. `join_field` is restricted to a whitelist (`correlation_id` / `request_id` / `trace_id` / `session_id` / `user_id` / `transaction_id` / `span_id` / `order_id`).

### Scenario 4: Agent exploring an unfamiliar project

```
1. Agent enters a new project, doesn't know where the logs live
2. list_sources() → see registered sources
3. If something's missing, register_source(name="new-service", path="...", format="jsonl")
   becomes queryable immediately
```

## Project layout

```
log-mcp/
├── pyproject.toml
├── DESIGN.md              # technical design doc
├── sources.example.yaml
├── log_mcp/
│   ├── __main__.py        # CLI entry point
│   ├── server.py          # MCP server + 7 tool schemas + structured error layer
│   ├── config.py          # sources.yaml loading and validation
│   └── engine.py          # DuckDB SQL engine + field projection layer
├── tests/                 # pytest tests (173 cases across engine/server/config)
├── docs/                  # design docs (DuckDB migration, agent-first evolution, etc.)
└── openspec/              # spec-driven development
    ├── specs/             # current capability specs
    └── changes/archive/   # archived change proposals
```

## Development

```bash
# Run tests
python -m pytest tests/ -v

# View current capability specs
openspec list --specs

# View active change proposals
openspec list
```

## Dependencies

- Python 3.11+
- `mcp>=1.0` — MCP SDK
- `duckdb>=1.2` — SQL query engine
- `pyyaml>=6.0` — config parsing

Test deps: `pytest` (not in runtime requirements).

## Design philosophy

> log-mcp is not trying to be "yet another log aggregation platform" — it's strictly **the log query frontend for AI agents**.

- **Read-only consumer**: doesn't touch the log producer's runtime, zero performance impact
- **Stateless**: DuckDB `:memory:` mode, every query is independent, no index maintenance
- **Agent-first**: every tool's input/output is shaped for LLM reasoning — sparse parameters, flat returns, actionable errors

Good fit:
- Debugging and triage during development / testing
- Single-machine or small-scale log retrieval
- Failure attribution in CI/CD pipelines

Not a fit:
- Petabyte-scale log warehouses (use Loki / ClickHouse / Elasticsearch)
- Cross-DC distributed log aggregation
- Real-time alerting and long-term archival

## Error responses

Every failure path returns a uniform structured JSON, so the agent can recover programmatically:

```json
{
  "error_code": "field_not_found",
  "detail": "字段引用失败: Referenced column \"foo\" not found",
  "suggestion": "请检查 field_filters 中的字段名是否正确，或调用 list_sources 查看实际 schema",
  "hints": {
    "candidate_fields": ["foo_id", "foo_bar"],
    "duckdb_error": "..."
  }
}
```

`error_code` enum:

| code | Trigger | Key `hints` field |
|------|---------|-------------------|
| `source_not_found` | Calling an unregistered source | `available_sources` |
| `field_not_found` | DuckDB BinderException / `field_map` referencing a missing column | `candidate_fields` (fuzzy match against actually observed columns) |
| `time_parse_error` | Invalid `since` / `until` | `valid_examples` |
| `join_field_not_allowed` | `cross_query.join_field` not in whitelist | full whitelist |
| `internal_error` | Any other unexpected exception | `exception_type` |

`detail` and `suggestion` strings are currently in Chinese (matching the project's primary documentation language); error codes and hint keys remain stable identifiers across locales.

## FAQ

**Q: `list_sources` returns `status: missing`**
The path doesn't exist or the MCP server process can't read it. Check that the path is absolute, the file exists, and the permissions allow read access.

**Q: Every tool call asks for authorization**
You haven't added the 7 tools to `.claude/settings.local.json` under `permissions.allow`. See [5. Hook it into Claude Code](#5-hook-it-into-claude-code) above.

**Q: Query results are too big and blow up the agent's context**
`query` / `tail` / `cross_query` automatically replace any single field value over 4 KB with a `<truncated:1.2MB>` placeholder by default (the four normalized fields `_timestamp` / `_level` / `_message` / `_source` are never truncated). If that's still too much:
- Pass `fields=["_timestamp", "_message", "correlation_id"]` to return only those fields (whitelisted fields are not truncated)
- Use `summary` to aggregate first, then drill in
- Tighten `field_filters` (e.g. `status: ">=400"`)

**Q: Why does `cross_query` require `join_value`?**
`join_value` pins the specific call chain ID you're tracing (e.g. one specific `correlation_id`). Omitting it would mean "every record in both sources within the time window" — expensive, noisy, and not what "trace" means. For full browsing use `query` with `since` / `limit`.

**Q: Why does `cross_query` default `since` to 1h?**
Cross-source UNION over big datasets without a time bound slows responses and inflates token usage. `1h` covers most triage cases; pass `since="1d"` etc. when you need more.

## License

MIT — see [LICENSE](LICENSE).
