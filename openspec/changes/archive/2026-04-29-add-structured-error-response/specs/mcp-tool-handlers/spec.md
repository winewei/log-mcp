# mcp-tool-handlers Spec Delta

## ADDED Requirements

### Requirement: Structured Error Response Schema
所有 tool handler 在异常路径上 MUST 返回统一结构化错误对象，schema 为 `{error_code, detail, suggestion, hints}` 四段式：`error_code` MUST 是预定义枚举之一（`source_not_found` / `field_not_found` / `time_parse_error` / `join_field_not_allowed` / `internal_error`）；`detail` MUST 为人类可读的中文错误说明；`suggestion` MUST 为单句可执行动作；`hints` MUST 为结构化字典，便于 Agent 程序化解析。

#### Scenario: source_not_found 包含可用源列表

- **WHEN** 通过 `call_tool("query", {"source": "ghost"})` 调用，且 registry 中不存在 `ghost`
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `source_not_found`，`hints.available_sources` MUST 是当前 registry 全部源名的列表，`suggestion` MUST 引导调用 `list_sources` 或 `register_source`

#### Scenario: field_not_found 包含候选字段名

- **WHEN** 通过 `call_tool("query", {"source": "x", "field_filters": {"foo": "bar"}})` 调用，且 `foo` 字段不存在于该源（DuckDB BinderException 或 field_map 引用失败）
- **THEN** 返回 JSON `error_code` MUST 等于 `field_not_found`，`hints` MUST 含候选字段名（基于已观察列做近似匹配，最多 3 个），`suggestion` MUST 引导检查 `field_map` 或调用 `list_sources` 查看真实 schema

#### Scenario: time_parse_error 包含合法示例

- **WHEN** 通过 `call_tool("query", {"source": "x", "since": "yesterday"})` 调用，`_parse_time` 抛 `ValueError`
- **THEN** 返回 JSON `error_code` MUST 等于 `time_parse_error`，`hints` MUST 含一组合法示例（如 ISO 8601 与 `30s/5m/1h/1d`），`suggestion` MUST 指明使用 ISO 8601 或相对值

#### Scenario: join_field_not_allowed 包含白名单

- **WHEN** 通过 `call_tool("cross_query", {"sources": [...], "join_field": "email"})` 调用，`email` 不在 `_ALLOWED_JOIN_FIELDS` 白名单
- **THEN** 返回 JSON `error_code` MUST 等于 `join_field_not_allowed`，`hints` MUST 含全部白名单字段名，`suggestion` MUST 指明使用白名单中的字段

#### Scenario: internal_error 包含异常类型

- **WHEN** `call_tool` 调用过程中发生未预期异常（不属于上述四类）
- **THEN** 返回 JSON `error_code` MUST 等于 `internal_error`，`hints` MUST 含触发异常的类型名（如 `RuntimeError`），进程 MUST 不崩溃

## MODIFIED Requirements

### Requirement: Source Lifecycle Handlers
`_handle_list_sources`、`_handle_register_source`、`_handle_unregister_source` MUST 基于模块级 `registry` 单例操作，并将结果编码为 `TextContent(type="text")`；非法输入经 `call_tool` 包装后 MUST 以结构化错误 JSON `{error_code, detail, suggestion, hints}` 形式返回，MUST 不再使用旧的 `{"error": ...}` 单字段格式，且 MUST 不向上抛异常。

#### Scenario: 列出空 registry

- **WHEN** registry 无任何源，调用 `_handle_list_sources({})`
- **THEN** 返回单个 TextContent，其 `text` 反序列化后为 `[]`

#### Scenario: 列出多源

- **WHEN** registry 已注册 2 个源并调用 `_handle_list_sources({})`
- **THEN** 返回列表含两个字典，每个字典 MUST 同时包含 `name/description/path/format` 与 `status/file_size_bytes/last_modified`

#### Scenario: 注册新源成功

- **WHEN** `_handle_register_source({name, description, path, format=jsonl})` 调用
- **THEN** 返回 `{"status": "registered", "name": <name>}`，且 `registry.get(name)` 能检索到

#### Scenario: 注册参数非法返回结构化错误

- **WHEN** 通过 `call_tool("register_source", {...format="invalid"})` 调用
- **THEN** 返回的 TextContent JSON MUST 含 `error_code` 字段且其值为 `internal_error`，MUST 含 `detail/suggestion/hints` 字段，MUST 不含旧 `error` 单字段，MUST 不向上抛 `ValueError`

#### Scenario: persist=True 写回 YAML

- **WHEN** registry 绑定了 `config_path` 且以 `persist=True` 注册源
- **THEN** 对应 `sources.yaml` 被重写，`load_config` 再次读取时能看到该源

#### Scenario: 注销存在的源

- **WHEN** `_handle_unregister_source({name})` 针对已存在源调用
- **THEN** 返回 `{"status": "unregistered", "name": <name>}`，后续 `registry.get(name)` MUST 抛 `KeyError`

#### Scenario: 注销不存在的源返回 source_not_found

- **WHEN** 通过 `call_tool("unregister_source", {"name": "ghost"})` 调用
- **THEN** 返回的 TextContent JSON `error_code` MUST 等于 `source_not_found`，`hints.available_sources` MUST 列出当前可用源名，MUST 不含旧 `error` 单字段

### Requirement: Query Handlers
`_handle_query`、`_handle_tail`、`_handle_summary`、`_handle_cross_query` MUST 将参数透传给 engine 层并序列化结果为 TextContent；源不存在、字段非法、时间格式非法、join_field 非法或其他异常经 `call_tool` 包装后 MUST 返回结构化错误 JSON `{error_code, detail, suggestion, hints}`，MUST 不再使用旧的 `{"error": ...}` 单字段格式，且 MUST 不向上抛异常。

#### Scenario: query 透传全部过滤参数

- **WHEN** `_handle_query({source, level, message_pattern, field_filters, since, until, limit, offset})` 调用
- **THEN** 返回 TextContent，其 JSON 含 `total_matched` 与 `entries` 结构，且受过滤条件影响

#### Scenario: query limit 被截断至 500

- **WHEN** `_handle_query({source, limit: 1000})` 调用
- **THEN** 传递给 engine 的 `limit` MUST 被截断为 500

#### Scenario: query 源不存在返回 source_not_found

- **WHEN** 通过 `call_tool("query", {"source": "ghost"})` 调用
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `source_not_found`，`hints.available_sources` MUST 列出当前可用源名，进程 MUST 不崩溃

#### Scenario: query 字段不存在返回 field_not_found

- **WHEN** 通过 `call_tool("query", {"source": "x", "field_filters": {"foo": "bar"}})` 调用，且 `foo` 字段在该源中不存在
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `field_not_found`，`hints` MUST 含候选字段名（最多 3 个近似匹配）

#### Scenario: query since 解析失败返回 time_parse_error

- **WHEN** 通过 `call_tool("query", {"source": "x", "since": "yesterday"})` 调用
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `time_parse_error`，`hints` MUST 含合法时间表达式示例

#### Scenario: tail 透传 agent_source 快捷过滤

- **WHEN** `_handle_tail({source, count, agent_source})` 调用
- **THEN** engine 收到的 `field_filters` 含 `agent_source` 键，entries 仅包含匹配该 agent 的条目

#### Scenario: summary 透传 percentile_fields 与 bucket_interval

- **WHEN** `_handle_summary({source, percentile_fields: ["duration_ms"], bucket_interval: "1m"})` 调用
- **THEN** 返回 JSON 同时含 `percentiles.duration_ms` 与 `time_buckets` 数组

#### Scenario: summary correlation_id 透传

- **WHEN** `_handle_summary({source, correlation_id: "run-001"})` 调用
- **THEN** engine 收到的 `field_filters` 含 `correlation_id` 键，统计结果受其过滤

#### Scenario: cross_query 成功

- **WHEN** `_handle_cross_query({sources: [a, b], join_field: correlation_id})` 调用，且两源均存在共享 correlation_id 的条目
- **THEN** 返回 JSON 含非空 `entries`

#### Scenario: cross_query sources 少于 2 返回结构化错误

- **WHEN** `_handle_cross_query({sources: ["only-one"], join_field: "x"})` 调用
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `internal_error`，`detail` MUST 说明 sources 至少需要 2 个日志源，MUST 不抛异常

#### Scenario: cross_query 源名不存在返回 source_not_found

- **WHEN** 通过 `call_tool("cross_query", {"sources": ["ghost", "also-ghost"], "join_field": "x"})` 调用
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `source_not_found`，`hints.available_sources` MUST 列出当前可用源名

#### Scenario: cross_query join_field 不在白名单返回 join_field_not_allowed

- **WHEN** 通过 `call_tool("cross_query", {"sources": [a, b], "join_field": "email"})` 调用，且 `email` 不在 `_ALLOWED_JOIN_FIELDS`
- **THEN** 返回 TextContent JSON `error_code` MUST 等于 `join_field_not_allowed`，`hints` MUST 含全部白名单字段
