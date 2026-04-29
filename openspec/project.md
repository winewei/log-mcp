# Project Context

## Purpose

log-mcp 是一个通用日志查询 MCP Server，目标是让 AI Agent（Claude Code 等）在开发/测试/排障过程中以参数化 SQL 的方式查询任意服务产出的结构化日志，替代 `grep` / `awk` 拼管道的低效路径。

核心定位是 **AI Agent 的日志查询前端**，明确不演进为通用日志聚合平台（不做 PB 级存储、跨机房分布式、告警、长期归档）。

## Tech Stack

- Python 3.11+
- MCP SDK：`mcp>=1.0`（PyPI）
- 查询引擎：`duckdb>=1.2`（嵌入式，`:memory:` 模式，无外部数据库）
- 配置：`pyyaml>=6.0`
- Transport：stdio（Claude Code 直连）
- 测试：`pytest` + tmp_path fixture

## Project Conventions

### Code Style

- 中文注释；模块顶部 docstring 简述职责
- Python imports 必须在文件顶部（除非有可信原因）
- 函数命名小写下划线；常量大写下划线；error_code 等枚举值用模块级常量
- 不写多段 docstring；只在 *why* 非显然时写一行注释
- 遵循"不要过度设计"原则：不写未使用的抽象、不为假想需求加扩展点

### Architecture Patterns

- **三层划分**：`server.py`（MCP Tool 暴露 + 错误层）/ `engine.py`（DuckDB SQL 构造与执行 + 字段裁剪层）/ `config.py`（源注册与持久化）
- **无状态**：MCP Server 进程不持有查询缓存；DuckDB `:memory:` 连接复用
- **参数化优先**：所有用户输入通过 `$N` 绑定到 SQL，禁止字符串拼接（`join_field` 用白名单限制因字段名必须拼入 SQL）
- **归一化字段**：通过 SELECT alias `AS _timestamp` 等完成，不引入中间数据结构；归一化字段名以 `_` 前缀区分原始字段
- **结构化错误**：所有异常路径统一走 `_make_error(code, detail, suggestion, hints)`，禁止裸 `{"error": ...}` 单字段返回
- **Token-aware 输出**：`query` / `tail` / `cross_query` 默认对 >4 KB 字段截断为占位符；归一化字段不参与截断

### Testing Strategy

- pytest + tmp_path fixture；测试日志数据写入 `tmp_path`，不在仓库内落盘
- 不 mock 数据库——直接用真实 DuckDB `:memory:`，保持集成真实性
- 每个 change 必须带回归测试覆盖新增 scenarios；BinderException / KeyError / ValueError 等错误路径单独测试
- 当前总用例数：173（engine: 64 / server: 49 / server_handlers: 30 / config: 30）

### Git Workflow

- 主分支 `main`；feature 工作通过 OpenSpec change 流程组织
- 提交信息格式：`<type>(<scope>): <subject>`（type 含 feat / fix / refactor / test / docs / chore）
- 每个 OpenSpec change 单次实施 commit + 必要的 fixer round commit + archive commit
- 禁止 `--no-verify` 跳过 hook

## Domain Context

### MCP（Model Context Protocol）

Anthropic 推出的协议，让 LLM Agent 通过 stdio / HTTP / SSE 调用外部工具。本项目用 stdio 直连 Claude Code，每个工具暴露一个 `inputSchema`（JSON Schema），返回 `list[TextContent]`。

### 日志生产端假设

log-mcp 是只读消费者，对生产端零强制要求。期望生产端：

- 输出 JSONL 或纯文本到文件（任何语言/框架）
- 包含 `timestamp` / `level` / `message` 三类字段（字段名可自定义，通过 `field_map` 映射到标准字段）
- 推荐携带 `correlation_id` / `trace_id` 等调用链 ID（cross_query 依赖）
- 推荐携带 `duration_ms` / `status` 等业务指标（summary 分位数与分组统计依赖）

### 字段命名约定

- `_` 前缀：MCP 归一化注入字段（`_timestamp` / `_level` / `_message` / `_source`）
- 无前缀：日志生产端原始字段，原样透传给 Agent

## Important Constraints

- **不持久化数据**：DuckDB `:memory:`，每次查询独立扫描文件
- **白名单限制**：`cross_query.join_field` 仅允许预定义字段（防字段名注入）
- **字段裁剪默认开启**：单字段 >4 KB 自动截断；保护 Agent 上下文
- **结构化错误强约束**：所有错误返回必须含 `error_code` / `detail` / `suggestion` / `hints`
- **不引入新运行时依赖**：除非有不可替代的能力需求

## External Dependencies

- DuckDB SQL 引擎：通过 `duckdb` Python 包内嵌，无独立服务
- MCP SDK：通过 `mcp` Python 包，封装 stdio transport 与 tool/resource 协议
- 无外部 API、消息队列、对象存储或第三方服务

## Active Specs

- `config-loader` — sources.yaml 加载与 SourceRegistry
- `mcp-tool-handlers` — 7 个 MCP tool 暴露与结构化错误响应
- `query-tool` / `tail-tool` / `summary-tool` — 三个核心查询工具行为
- `cross-query-tool` — UNION ALL timeline 跨源关联
- `duckdb-query-engine` — DuckDB SQL 构造与参数化
- `project-dependencies` — 运行时依赖清单

`openspec list --specs` 可见全部当前能力规格；`openspec/changes/archive/` 保留全部历史变更提案。
