# LOG MCP Server 技术方案

## 1. 使用场景

AI Agent（如 Claude Code）在辅助开发/测试/排障时，需要高频访问结构化日志。传统方式依赖 `grep`/`awk` 拼管道或用户手工粘贴日志片段，存在效率瓶颈。

log-mcp 以 MCP 协议向 Agent 暴露参数化日志查询能力，覆盖以下典型场景：

| 场景 | 诉求 | log-mcp 工具 |
|------|------|--------------|
| 代码变更后快速定位报错 | 按时间窗口 + 级别过滤 | `query` / `tail` |
| 单次请求/测试的调用链排障 | 按 `correlation_id` / `trace_id` 精确匹配 | `query` + `field_filters` |
| 服务健康度聚合 | 按维度分组计数、分位数统计、时间桶趋势 | `summary` |
| 跨服务/跨端链路重建 | 多日志源通过共享字段 INNER JOIN | `cross_query` |
| Agent 探索未知项目 | 动态注册日志源，无需重启 | `register_source` |

**约束**：log-mcp 是**只读消费者**，通过文件系统读取日志文件，不侵入日志生产端运行时。

## 2. 架构

```
  服务端 A ────→ JSONL 文件 ┐
  服务端 B ────→ JSONL 文件 ├──→ log-mcp（DuckDB SQL 引擎） ──→ Claude Code Agent
  客户端   ────→ JSONL 文件 ┘            ↑                        ↑
                                     stdio transport        参数化 tool 调用
```

- **日志生产端**：任何输出 JSONL 或纯文本日志的服务（Python/Go/Node/Rust/...）
- **log-mcp**：读取配置的日志路径，用 DuckDB `read_json_auto` / `read_csv` 加载，执行 SQL 过滤聚合
- **Agent**：通过 MCP tool 调用，输入结构化参数，获得 JSON 返回

## 3. 项目结构

```
log-mcp/
├── pyproject.toml
├── CLAUDE.md
├── DESIGN.md
├── README.md
├── sources.example.yaml
├── log_mcp/
│   ├── __init__.py          # 版本号
│   ├── __main__.py          # CLI 入口，解析 --config
│   ├── server.py            # MCP Server 定义，注册 7 个 tools
│   ├── config.py            # sources.yaml 加载与校验
│   └── engine.py            # DuckDB SQL 查询引擎
├── tests/                   # pytest 测试
└── openspec/                # 规格驱动开发
    ├── specs/               # 当前能力规格
    └── changes/archive/     # 已归档变更提案
```

## 4. 配置格式 `sources.yaml`

```yaml
sources:
  api-server:
    description: "后端 API 服务日志"
    path: "/var/log/api/request.jsonl"
    rotation: numeric          # numeric: .1 .2 .3 | date: .2026-04-04 | none
    format: jsonl
    field_map:
      timestamp: ts            # 源字段 → MCP 标准字段
      level: level
      message: event

  worker:
    description: "后台任务日志"
    path: "/var/log/worker/worker.jsonl"
    rotation: numeric
    format: jsonl
    field_map:
      timestamp: ts
      level: level
      message: event

  go-service:
    description: "Go 微服务运行日志"
    path: "/var/log/service.jsonl"
    rotation: date
    format: jsonl
    field_map:
      timestamp: time
      level: severity
      message: msg
```

### 配置字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | string | 是 | 人类/Agent 可读的描述 |
| `path` | string | 是 | 主日志文件的绝对路径 |
| `rotation` | enum | 否 | `numeric`（默认）/ `date` / `none` |
| `format` | enum | 否 | `jsonl`（默认）/ `text` |
| `field_map` | object | 否 | 源字段名到标准字段名的映射 |

### 标准字段（归一化后）

MCP 查询统一使用这三个标准字段名，`field_map` 负责翻译：

| 标准字段 | 含义 | 默认源字段名（不配 field_map 时）|
|----------|------|------|
| `timestamp` | 事件时间 | `timestamp` |
| `level` | 日志级别 | `level` |
| `message` | 事件描述 | `message` |

其余字段**原样透传**，Agent 可通过 `field_filters` 按任意原始字段查询。

## 5. MCP Tools 定义

### 5.1 `list_sources`

列出所有已注册的日志源及其状态。

**参数**：无

**返回**：
```json
[
  {
    "name": "api-server",
    "description": "后端 API 服务日志",
    "path": "/var/log/api/request.jsonl",
    "format": "jsonl",
    "status": "ok",
    "file_size_bytes": 1048576,
    "last_modified": "2026-04-04T10:30:00Z"
  }
]
```

`status` 枚举：`ok`（文件存在且非空）/ `missing`（文件不存在）/ `empty`（文件为空）

### 5.2 `query`

主力查询工具。按条件过滤日志条目，返回匹配结果。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 源名称 |
| `level` | string | 否 | 日志级别过滤：`error` / `warning` / `info` / `debug` |
| `message_pattern` | string | 否 | 正则匹配归一化后的 `message` 字段 |
| `field_filters` | object | 否 | 任意字段过滤，见下方语法 |
| `since` | string | 否 | 起始时间：ISO 8601 或相对值 `30s` `5m` `1h` `1d` |
| `until` | string | 否 | 结束时间，同上 |
| `limit` | number | 否 | 返回条数上限，默认 50，最大 500 |
| `offset` | number | 否 | 跳过前 N 条结果，默认 0 |

**`field_filters` 语法**：

```json
{
  "user_id": "42",
  "status": ">=400",
  "path": "~^/api/v1",
  "correlation_id": "run-abc-123",
  "env": "!production"
}
```

- 纯字符串：精确匹配
- `~` 前缀：正则匹配（`"~pattern"`）
- `>=` `<=` `>` `<` 前缀：数值比较
- `!` 前缀：取反（`"!production"` 排除该值）

**返回**：
```json
{
  "total_matched": 12,
  "entries": [
    {
      "_source": "api-server",
      "_timestamp": "2026-04-04T10:00:01Z",
      "_level": "error",
      "_message": "auth_failed",
      "request_id": "uuid-1",
      "correlation_id": "run-abc-123",
      "method": "POST",
      "path": "/api/v1/auth/login",
      "status": 500,
      "duration_ms": 45,
      "detail": "invalid token signature"
    }
  ]
}
```

归一化字段以 `_` 前缀返回（`_source`、`_timestamp`、`_level`、`_message`），原始字段原样保留。

### 5.3 `tail`

从文件末尾反向读取最近的日志条目。最快路径，Agent 改完代码后的第一个调用。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 源名称 |
| `count` | number | 否 | 返回条数，默认 20，最大 200 |
| `level` | string | 否 | 过滤级别 |
| `agent_source` | string | 否 | 快捷过滤，等价于 `field_filters.agent_source` |

**返回**：同 `query`，但从最新到最旧排序。

### 5.4 `summary`

聚合统计，Agent 用来快速判断服务健康状况。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 是 | 源名称 |
| `since` | string | 否 | 时间窗口，默认 `5m` |
| `agent_source` | string | 否 | 按 agent 过滤 |
| `correlation_id` | string | 否 | 按调用链过滤 |
| `group_by` | string | 否 | 聚合维度：`path` / `level` / 任意字段名 |
| `percentile_fields` | string[] | 否 | 需要计算 p50/p95/p99 的数值字段列表 |
| `bucket_interval` | string | 否 | 时间桶粒度：`1m` / `5m` / `1h` |

**返回**：
```json
{
  "time_range": ["2026-04-04T10:00:00Z", "2026-04-04T10:05:32Z"],
  "total": 142,
  "level_counts": {"error": 3, "warning": 5, "info": 134},
  "top_messages": [
    {"message": "http_request", "count": 130},
    {"message": "auth_failed", "count": 3}
  ],
  "groups": {
    "/api/v1/auth/login": {"total": 45, "errors": 2},
    "/api/v1/users": {"total": 30, "errors": 1}
  },
  "percentiles": {
    "duration_ms": {"p50": 35.0, "p95": 180.0, "p99": 850.0}
  },
  "time_buckets": [
    {"bucket": "2026-04-04T10:00:00Z", "total": 45, "errors": 1},
    {"bucket": "2026-04-04T10:01:00Z", "total": 62, "errors": 2}
  ]
}
```

`percentiles` 和 `time_buckets` 仅在对应参数存在时返回。

### 5.5 `cross_query`

跨源关联查询，通过共享字段（如 `correlation_id`）对多个日志源执行 INNER JOIN。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sources` | string[] | 是 | 参与关联的源名称列表，至少 2 个 |
| `join_field` | string | 是 | 用于 JOIN 的字段名（白名单限定） |
| `level` | string | 否 | 级别过滤，应用于所有源 |
| `since` | string | 否 | 时间范围起点 |
| `limit` | number | 否 | 返回条数上限，默认 50 |

**安全约束**：`join_field` 必须在白名单内（`correlation_id` / `request_id` / `trace_id` / `session_id` / `user_id` / `transaction_id` / `span_id` / `order_id`），防止 SQL 注入。

**返回**：
```json
{
  "entries": [
    {"_source": "api-server", "_timestamp": "...", "correlation_id": "run-001", "...": "..."}
  ]
}
```

### 5.6 `register_source`

动态注册新的日志源。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 源名称，唯一标识 |
| `description` | string | 是 | 描述 |
| `path` | string | 是 | 日志文件绝对路径 |
| `format` | string | 否 | `jsonl`（默认）/ `text` |
| `rotation` | string | 否 | `numeric`（默认）/ `date` / `none` |
| `field_map` | object | 否 | 字段映射 |
| `persist` | boolean | 否 | 默认 `false`；`true` 则追加写入 sources.yaml |

**返回**：
```json
{"status": "registered", "name": "api-server"}
```

### 5.7 `unregister_source`

移除已注册的日志源。

**参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 源名称 |
| `persist` | boolean | 否 | 默认 `false`；`true` 则从 sources.yaml 中删除 |

**返回**：
```json
{"status": "unregistered", "name": "api-server"}
```

## 6. 实现细节

### 6.1 DuckDB 查询引擎 (`engine.py`)

engine.py 是所有查询类 tool 的核心，封装以下能力：

- **文件发现**：`discover_files(path, rotation)` 按 numeric/date/none 规则列出主文件 + 轮转历史
- **SQL 生成**：JSONL 用 `read_json_auto(files, ignore_errors=true)`，text 用 `read_csv` 单列模式
- **字段归一化**：在 SELECT 层通过 `AS _timestamp` 等别名完成，避免中间结构
- **过滤翻译**：`_parse_filter_expr()` 将 5 种语法映射到参数化 SQL：
  - 精确：`col = $N`
  - 正则：`regexp_matches(col, $N)`
  - 数值：`CAST(col AS DOUBLE) >= $N`
  - 取反：`col != $N OR col IS NULL`
- **参数化**：所有用户输入通过 DuckDB `$1, $2, ...` 绑定，杜绝拼接
- **连接管理**：模块级 `:memory:` 连接复用，无磁盘文件

### 6.2 日志读取

- **JSONL 解析**：DuckDB 原生支持，自动推断 schema，跳过非法行
- **text 模式**：单列 VARCHAR，整行作为 `_message`，仅支持 `message_pattern` 过滤
- **轮转发现**：
  - `numeric`：主文件 + `.1`/`.2`/`.3`... 后缀
  - `date`：匹配 `base.YYYY-MM-DD.ext` 的文件，按日期倒序
  - `none`：仅主文件

### 6.3 MCP Server (`server.py`)

使用 `mcp` SDK 的标准模式：

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("log-mcp")

@server.list_tools()
async def list_tools() -> list[Tool]:
    # 返回 7 个 tool 的 schema 定义
    ...

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # 路由到对应处理函数，统一异常捕获
    ...

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
```

### 6.4 CLI 入口 (`__main__.py`)

```python
import argparse
import asyncio

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="sources.yaml 路径", default=None)
    args = parser.parse_args()
    asyncio.run(run_server(args.config))

if __name__ == "__main__":
    main()
```

## 7. 依赖

```toml
[project]
name = "log-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "duckdb>=1.2",
    "mcp>=1.0",
    "pyyaml>=6.0",
]
```

额外传递依赖：`pytz`（DuckDB `time_bucket` 函数需要）。

## 8. 对日志生产端的期望

log-mcp 对生产端**零强制要求**——任何产出 JSONL 或纯文本的服务都可接入。但若希望充分发挥查询能力，建议生产端在日志中包含：

### 8.1 基础字段（几乎所有日志库都有）

```json
{
  "ts": "2026-04-04T10:00:01+00:00",
  "level": "info",
  "event": "http_request"
}
```

### 8.2 请求上下文字段（便于按调用链检索）

```json
{
  "request_id": "uuid",
  "correlation_id": "run-abc-123",
  "trace_id": "hex-span-id"
}
```

### 8.3 业务指标字段（便于聚合统计）

```json
{
  "method": "POST",
  "path": "/api/v1/auth/login",
  "status": 500,
  "duration_ms": 45,
  "user_id": 42
}
```

### 8.4 推荐的日志输出方式

- **Python**：`structlog.processors.JSONRenderer()` + `logging.handlers.RotatingFileHandler`
- **Go**：`zerolog` 或 `zap` 的 JSON 编码器
- **Node.js**：`pino` 默认 JSON 输出
- **Java**：`logback-json-encoder` 或 `logstash-logback-encoder`

## 9. Agent 典型使用流程

### 场景 A：快速定位测试失败

```
1. Agent 执行集成测试，收到 500 错误响应
2. tail(source="api-server", count=10, level="error")
   → 最新 10 条错误，确认是服务端报错而非网络问题
3. query(source="api-server",
         field_filters={"correlation_id": "test-run-001"})
   → 拉取该次测试的完整请求链，定位具体错误位置
4. Agent 基于日志细节修复代码，回归测试
```

### 场景 B：监控代码变更后的服务健康度

```
1. Agent 提交代码改动触发 CI
2. summary(source="api-server", since="5m",
           percentile_fields=["duration_ms"],
           bucket_interval="1m")
   → 错误计数、响应时间分位数、按分钟分桶趋势
3. 若 errors > 0 或 p95 明显劣化，回到 query 定位
```

### 场景 C：跨服务链路重建

```
cross_query(
  sources=["api-server", "worker", "client-log"],
  join_field="correlation_id",
  level="error",
  since="10m"
)
→ 自动关联前端操作、网关入口、后端任务的错误日志，
  还原完整故障时序
```
