# 测试覆盖缺口与补全方案

> **状态：已实施（2026-04-16）**
>
> 文档中提出的 3 个 changes（`add-config-tests` / `add-server-handler-tests` / `add-server-smoke-test`）均已实施并归档。
> 当前测试覆盖：`tests/test_config.py` 30 用例 + `tests/test_engine.py` 64 用例 + `tests/test_server.py` 49 用例 + `tests/test_server_handlers.py` 30 用例 = **173 用例**。
> 本文档保留作为决策记录。

## 背景

当前工程 48 个测试全部集中于 `tests/test_engine.py`，只覆盖 SQL 引擎层（`log_mcp/engine.py`）。其余两个核心模块（`log_mcp/config.py`、`log_mcp/server.py`）**完全没有测试保护**，这些恰恰是近期动态调整日志源、Claude Code 交互时频繁走到的代码路径。

## 现状统计

| 文件 | 行数 | 职责 | 测试覆盖 |
|---|---|---|---|
| `log_mcp/engine.py` | 557 | DuckDB 查询引擎 | ✅ 48 用例，覆盖 discover_files / parse_time / parse_filter_expr / query_entries / tail_entries / summarize_entries / cross_query_entries |
| `log_mcp/config.py` | 172 | YAML 加载、源注册表、持久化 | ❌ 零覆盖 |
| `log_mcp/server.py` | 334 | MCP 7 个 tool handler、file_status、schema | ❌ 零覆盖 |
| `log_mcp/__main__.py` | 44 | CLI 入口 | ❌ 零覆盖（可接受） |

**测试基础设施**：已存在 `tests/conftest.py`（130 行）与 pytest fixtures，新增测试沿用即可。

## 缺口 1：`config.py` 配置加载与源注册表

### 未覆盖的函数

- `_validate_source(name, cfg) -> dict`
  - 必填字段缺失（如 `path` 为空）应抛错
  - `format` 非法值（非 jsonl/text）应抛错
  - `rotation` 非法值（非 numeric/date/none）应抛错
  - `field_map` 缺省时应填充默认 `timestamp/level/message`
  - `field_map` 部分提供时应与默认合并

- `load_config(config_path) -> dict[str, dict]`
  - 配置文件不存在：抛 `FileNotFoundError` 或等效错误
  - YAML 语法错误：抛 yaml 解析错误
  - 顶层缺少 `sources` 键：按空 registry 处理或报错（需先读代码确认实际行为）
  - 多个源同名：抛错
  - 正常加载多源：返回结构正确

- `class SourceRegistry`
  - `register(name, cfg)`：首次注册写入内存
  - `register` 重名：根据实现决定是覆盖还是抛错（需先读代码确认）
  - `unregister(name)`：移除存在的源
  - `unregister` 不存在的源：抛错或静默
  - `persist_to_yaml(path)`：写入后再 `load_config` 应一致
  - `persist_to_yaml` 对不存在的父目录：行为需定义（创建或报错）

### 价值

- 这些是配置入口，一旦错误所有查询都废；是"必须可信"的边界。
- `vpn-api` 重注册事件暴露过真实使用路径，必须有回归保护。

## 缺口 2：`server.py` MCP 工具入口层

### 未覆盖的函数

- `_file_status(path) -> dict`
  - 文件存在：返回 `status=ok` + size + mtime
  - 文件不存在：返回 `status=missing`
  - 路径是目录而非文件：行为需定义
  - 无读权限：行为需定义（在 CI 中可 chmod 构造）

- 7 个 `_handle_*(args) -> list[TextContent]`
  - `_handle_list_sources`：空 registry / 多源情况下返回结构
  - `_handle_query`：源名不存在 → 返回友好错误；必填参数缺失；参数透传到 engine
  - `_handle_tail`：同上
  - `_handle_summary`：同上；`percentile_fields` / `bucket_interval` 的透传
  - `_handle_cross_query`：`sources` < 2 时的校验；`join_field` 透传
  - `_handle_register_source`：新源注册成功；persist=true 时回写 yaml；重名冲突
  - `_handle_unregister_source`：存在源可注销；不存在源的错误提示

- tool schema（`list_tools` 返回的 7 个 Tool 定义）
  - 确保 `inputSchema` 是合法 JSON Schema（可 `jsonschema.validate` 一个最小参数验证）
  - 必填字段清单与文档一致

### 价值

- Handler 层是 MCP 协议暴露面，任何破坏都直接影响 Agent 交互。
- 真实使用中 Agent 会传入各种边界参数（多余字段、类型不符等），需要保底行为。

## 缺口 3：端到端 Smoke Test（可选）

没有任何测试覆盖 `run_server` 的初始化流程：加载配置 → 构造 Server → 注册 tool。若未来改动 SDK 初始化顺序，风险无法被测试拦截。

此项优先级最低，可以只做一个"能启动、能列出 7 个 tool"的烟雾测试。

## 建议拆分（3 个 change）

### Change 1：`add-config-tests`（P0）

给 `log_mcp/config.py` 加单元测试，覆盖 `_validate_source` / `load_config` / `SourceRegistry` 三处。

- 新 spec：`config-loader`（ADDED）
- 用 pytest + tmp_path fixture 构造 yaml 文件
- 覆盖正常路径与所有错误分支
- 目标：该文件 ≥90% 行覆盖

### Change 2：`add-server-handler-tests`（P1）

给 `log_mcp/server.py` 的 7 个 handler 与 `_file_status` 加单元测试。

- 新 spec：`mcp-tool-handlers`（ADDED）
- 用真实 `SourceRegistry` + 引擎（不 mock 引擎，保持集成真实性）
- 构造小型 JSONL 日志文件作为测试源
- 覆盖成功路径、源不存在、参数非法等分支
- 验证 `list_tools` 返回的 schema 合法

### Change 3：`add-server-smoke-test`（P2，可选）

一个最小 smoke test：启动 `run_server`（或直接构造 server 对象），列出 tool，断言 7 个工具都在。

- 修改现有 spec 而非新增（server.py 本身无公开 spec 则归入 mcp-tool-handlers）
- 是否作为独立 change 还是并入 Change 2 由 docs-to-changes 决策

## 共同约束

- 所有新测试放 `tests/` 下，沿用 `tests/conftest.py` 的 fixture 风格
- 临时文件走 `tmp_path`，不在仓库内落盘
- 不引入新运行时依赖；测试依赖仅限 `pytest`
- 注释与断言信息中文
