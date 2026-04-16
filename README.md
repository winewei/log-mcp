# log-mcp

通用日志查询 MCP Server，为 AI Agent 提供结构化日志的实时查询、聚合与跨源关联能力。

基于 DuckDB SQL 引擎直接读取 JSONL/文本日志文件，零外部数据库依赖，适用于任意语言与框架产出的日志。

## 解决的问题

AI Agent（如 Claude Code）在辅助开发与测试时，频繁需要回答以下问题：

- **"我刚改的代码有没有报错？"** — 需要按时间窗口查询服务端日志
- **"这次测试请求为什么失败？"** — 需要按 `correlation_id` / `trace_id` 定位具体调用链
- **"最近 5 分钟的错误率是多少？"** — 需要聚合统计与分位数分析
- **"客户端点击到服务端处理的完整链路是什么？"** — 需要跨多个日志源关联查询

传统方式要求 Agent 执行 `grep` / `awk` 拼管道或让用户手动粘贴日志，效率低且易出错。log-mcp 以 MCP 协议暴露结构化查询能力，让 Agent 以参数化 SQL 的方式精准检索日志。

## 特性

- **语言/框架无关**：任何产出 JSONL 或纯文本日志的服务都可接入（Python/Go/Node/Java/Rust ...）
- **DuckDB SQL 引擎**：过滤、排序、聚合、JOIN 全部在引擎层完成，性能可承载数百万行
- **参数化查询**：所有用户输入通过 `$N` 参数绑定，杜绝 SQL 注入
- **多源字段归一化**：通过 `field_map` 将不同服务的字段名映射到统一的 `_timestamp` / `_level` / `_message`
- **日志轮转感知**：自动发现 numeric（`.1/.2/.3`）、date（`.YYYY-MM-DD`）、none 三种轮转模式的历史文件
- **动态注册**：无需重启即可增删日志源，可选持久化到配置文件
- **跨源 JOIN**：通过 `correlation_id` 等字段在多个日志源间执行 INNER JOIN，重建分布式调用链
- **零运维负担**：stdio transport 直连，内存模式运行，不占用额外端口

## 7 个 MCP Tools

| Tool | 说明 |
|------|------|
| `list_sources` | 列出已注册的日志源及其文件状态 |
| `query` | 主力查询：级别/正则/任意字段/时间范围过滤，支持 `offset` 分页 |
| `tail` | 反向取最新 N 条，精确返回不受过滤命中率影响 |
| `summary` | 聚合统计：total / level_counts / top_messages / groups，支持分位数（p50/p95/p99）和时间桶（1m/5m/1h） |
| `cross_query` | 跨源关联查询：通过共享字段对多个源执行 INNER JOIN |
| `register_source` | 动态注册日志源，可选写入 `sources.yaml` |
| `unregister_source` | 注销日志源 |

## 快速开始

### 1. 安装

```bash
git clone <repo-url> log-mcp
cd log-mcp
pip install -e .
```

要求 Python 3.11+。依赖自动安装：`mcp` / `duckdb` / `pyyaml`。

### 2. 准备日志

确认你的服务会把日志写到**文件**里，并且格式满足以下任一种：

- **JSONL（推荐）**：每行一条 JSON，字段扁平，如 structlog / zerolog / pino / zap 默认输出
- **纯文本**：每行一条记录，需在 `sources.yaml` 中指定 `format: text`

记下日志文件的**绝对路径**，以及文件中代表时间戳、级别、消息的字段名（下一步要用）。

### 3. 配置 `sources.yaml`（可选）

见下方 [配置格式](#配置格式-sourcesyaml)。若选择"纯动态注册"模式，可跳过此步，启动后让 Agent 调用 `register_source` 添加。

### 4. 启动服务

```bash
# 带配置文件
python -m log_mcp --config /absolute/path/to/sources.yaml

# 纯动态注册模式（运行时通过 register_source 添加源）
python -m log_mcp
```

### 5. 接入 Claude Code

在项目的 `.claude/settings.local.json` 中添加 MCP Server 与权限清单。把 7 个 tool **全部加入 `permissions.allow`**，避免每次调用都弹出授权对话框：

```json
{
  "mcpServers": {
    "log": {
      "command": "python",
      "args": ["-m", "log_mcp", "--config", "/absolute/path/to/sources.yaml"]
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

重启 Claude Code 后，输入 `/mcp` 应能看到 `log` Server 已连接。

### 6. 开始使用

直接用自然语言提问即可，Agent 会自动选择合适的 tool：

- "最近 5 分钟有没有 error？" → `summary` + `query`
- "查看 api-server 最新 20 条日志" → `tail`
- "这次测试 run-abc-123 的完整调用链" → `query` with `correlation_id`
- "客户端点击到服务端响应的链路" → `cross_query`

也可手工在对话里让 Agent 调用：`list_sources` 看有哪些源、`register_source` 新增一个。

## 配置格式 `sources.yaml`

> **重要**：`field_map` 必须与日志文件**实际字段名完全一致**。例如文件里时间字段叫 `timestamp`，就不能写成 `ts`，否则查询会因为 DuckDB 找不到列直接报 `BinderException`。若不确定，可先 `head -n 1` 看一条真实日志再配置。

```yaml
sources:
  # 示例 1：Python structlog 输出的 JSONL
  api-server:
    description: "后端 API 服务日志"
    path: "/var/log/api/request.jsonl"
    rotation: numeric          # numeric | date | none
    format: jsonl              # jsonl | text
    field_map:
      timestamp: ts            # 源字段 → 标准字段
      level: level
      message: event

  # 示例 2：Go zerolog 输出，按日期轮转
  worker:
    description: "后台任务执行日志"
    path: "/var/log/worker/worker.log"
    rotation: date
    format: jsonl
    field_map:
      timestamp: time
      level: severity
      message: msg

  # 示例 3：测试框架输出的测试运行日志
  test-runner:
    description: "集成测试运行日志"
    path: "/tmp/test-run.jsonl"
    rotation: none
    format: jsonl
    # field_map 省略 → 默认使用 timestamp/level/message

  # 示例 4：传统应用服务器 access log（纯文本）
  nginx:
    description: "Nginx 访问日志"
    path: "/var/log/nginx/access.log"
    rotation: date
    format: text
```

### 标准字段（归一化后）

查询层统一通过以下字段操作，`field_map` 负责从源字段名翻译：

| 标准字段 | 含义 | 默认源字段名 |
|----------|------|--------------|
| `_timestamp` | 事件时间（ISO 8601 或可解析时间串） | `timestamp` |
| `_level` | 日志级别（error/warning/info/debug） | `level` |
| `_message` | 事件描述 | `message` |
| `_source` | 日志源名称（MCP 注入） | — |

原始字段全部透传，Agent 可通过 `field_filters` 按任意字段查询。

### 字段过滤语法

`query` 和 `summary` 的 `field_filters` 参数支持 5 种语法：

```json
{
  "user_id": "42",                    // 精确匹配
  "status": ">=400",                  // 数值比较（>= <= > <）
  "path": "~^/api/v1",                // 正则匹配（~ 前缀）
  "env": "!production",               // 取反匹配（! 前缀）
  "correlation_id": "run-abc-123"     // 精确匹配
}
```

### 时间表达式

`since` / `until` 参数支持两种格式：

- ISO 8601：`2026-04-15T10:00:00Z`
- 相对时间：`30s` / `5m` / `1h` / `1d`

## 典型使用流程

### 场景 1：定位测试失败的根因

```
1. Agent 执行集成测试，收到 500 错误
2. tail(source="api-server", count=10, level="error")
   → 看到最新错误：auth_failed
3. query(source="api-server", field_filters={"correlation_id": "run-001"})
   → 拉取该次测试完整请求链，定位具体错误原因
4. Agent 修复代码后重新测试
```

### 场景 2：监控代码变更后的错误率

```
1. Agent 修改服务端代码后触发 CI
2. summary(source="api-server", since="5m",
           percentile_fields=["duration_ms"],
           bucket_interval="1m")
   → 获取最近 5 分钟错误计数、p50/p95/p99 响应时间、按分钟分桶
3. 如 errors > 0 或 p95 飙升，回到 query 定位具体问题
```

### 场景 3：跨端链路追踪

```
cross_query(
  sources=["api-server", "test-runner"],
  join_field="correlation_id",
  level="error",
  since="10m"
)
→ 自动关联客户端操作与服务端响应，还原完整交互时序
```

### 场景 4：Agent 自主探索未知项目

```
1. Agent 进入新项目，不知道日志在哪
2. list_sources() → 了解当前已注册的日志源
3. 若缺少某个源，register_source(name="new-service", path="...", format="jsonl")
   动态注册后立即可查
```

## 项目结构

```
log-mcp/
├── pyproject.toml
├── DESIGN.md              # 技术设计文档
├── sources.example.yaml
├── log_mcp/
│   ├── __main__.py        # CLI 入口
│   ├── server.py          # MCP Server + 7 个 tool schemas
│   ├── config.py          # sources.yaml 加载与校验
│   └── engine.py          # DuckDB SQL 引擎
├── tests/                 # pytest 测试（48 个用例）
└── openspec/              # 规格驱动开发
    ├── specs/             # 当前能力规格
    └── changes/archive/   # 已归档的变更提案
```

## 开发

```bash
# 运行测试
python -m pytest tests/ -v

# 查看当前能力规格
openspec list --specs

# 查看活跃变更提案
openspec list
```

## 依赖

- Python 3.11+
- `mcp>=1.0` — MCP SDK
- `duckdb>=1.2` — SQL 查询引擎
- `pyyaml>=6.0` — 配置解析
- `pytz` — DuckDB `time_bucket` 函数依赖（传递安装）

## 设计理念

> log-mcp 不想做"又一个日志聚合平台"，只做 **AI Agent 的日志查询前端**。

- **只读消费者**：不侵入日志生产端运行时，零性能影响
- **无状态**：DuckDB `:memory:` 模式，每次查询独立，无索引维护成本
- **Agent-first**：所有 tool 的输入/输出都针对 LLM 的推理模式优化——参数稀疏、返回结构扁平、错误信息具备可操作性

适合：
- 开发/测试阶段的调试与排障
- 单机或小规模部署的日志检索
- CI/CD 流水线中的故障归因

不适合：
- PB 级日志仓库（请使用 Loki / ClickHouse / Elasticsearch）
- 跨机房的分布式日志聚合
- 实时告警与长期归档

## 常见问题

**Q: 调用 tool 时返回 `BinderException: Referenced column "xxx" not found`**
源配置的 `field_map` 与日志实际字段名不一致。读一条真实日志核对，通过 `unregister_source` + `register_source` 重新注册即可（或直接改 `sources.yaml` 后重启）。

**Q: `list_sources` 返回 `status: missing`**
文件路径不存在或 MCP Server 进程无权读取。检查路径是否为绝对路径、文件是否存在、权限是否允许。

**Q: 每次调用 tool 都弹授权**
未把 7 个 tool 加入 `.claude/settings.local.json` 的 `permissions.allow`，参照上方 [5. 接入 Claude Code](#5-接入-claude-code)。

**Q: 查询返回结果过大被截断**
`tail` / `query` 返回全字段；若日志含大 body/headers/cookie，建议：
- 用 `summary` 先聚合再针对性下钻
- 用 `field_filters` 收窄范围（如 `status: ">=400"`）
- 用 `count` / `limit` 控制条数

## License

MIT
