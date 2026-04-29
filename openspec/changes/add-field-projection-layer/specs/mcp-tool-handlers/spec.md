# mcp-tool-handlers Specification Delta

## MODIFIED Requirements

### Requirement: Tool Schema Exposure
`list_tools` MUST 返回恰好 7 个 `Tool` 实例，涵盖 `list_sources`、`query`、`tail`、`summary`、`register_source`、`unregister_source`、`cross_query`，每个 Tool 的 `inputSchema` MUST 是合法的 JSON Schema 并声明正确的必填字段，以便 MCP 客户端据此构造请求。`query` 与 `tail` 两个 Tool 的 `inputSchema.properties` MUST 包含可选参数 `fields`，类型为 `array`，`items.type` 为 `string`，描述其用于字段白名单裁剪。

#### Scenario: 七个 tool 均已暴露

- **WHEN** 测试调用 `await list_tools()`
- **THEN** 返回的 Tool 名称集合恰好为 `{list_sources, query, tail, summary, register_source, unregister_source, cross_query}`

#### Scenario: inputSchema 通过 JSON Schema 校验

- **WHEN** 对每个 Tool 的 `inputSchema` 调用 `jsonschema.Draft202012Validator.check_schema`
- **THEN** 均 MUST 不抛异常，证明是合法 Draft 2020-12 JSON Schema

#### Scenario: 必填字段契约稳固

- **WHEN** 读取 `query`、`tail`、`summary` 的 `required`
- **THEN** 三者 MUST 均为 `["source"]`；`register_source.required` MUST 为 `["name", "description", "path"]`；`unregister_source.required` MUST 为 `["name"]`；`cross_query.required` MUST 为 `["sources", "join_field"]`

#### Scenario: cross_query sources 最少两项

- **WHEN** 读取 `cross_query` 的 `inputSchema.properties.sources`
- **THEN** 其 `type` MUST 为 `array` 且 `minItems` MUST 为 2

#### Scenario: query/tail 暴露 fields 可选参数

- **WHEN** 读取 `query` 与 `tail` 的 `inputSchema.properties.fields`
- **THEN** 两者 MUST 存在且 `type` 为 `array`，`items.type` 为 `string`，`fields` MUST 不出现在 `required` 中

### Requirement: Query Handlers
`_handle_query`、`_handle_tail`、`_handle_summary`、`_handle_cross_query` MUST 将参数透传给 engine 层并序列化结果为 TextContent；源不存在或参数非法经 `call_tool` 包装后 MUST 返回错误 JSON 而非抛出。`_handle_query` 与 `_handle_tail` MUST 将客户端传入的 `fields` 参数透传至 engine 层，由 engine 在结果序列化前应用公共裁剪层。

#### Scenario: query 透传全部过滤参数

- **WHEN** `_handle_query({source, level, message_pattern, field_filters, since, until, limit, offset})` 调用
- **THEN** 返回 TextContent，其 JSON 含 `total_matched` 与 `entries` 结构，且受过滤条件影响

#### Scenario: query limit 被截断至 500

- **WHEN** `_handle_query({source, limit: 1000})` 调用
- **THEN** 传递给 engine 的 `limit` MUST 被截断为 500

#### Scenario: query 源不存在

- **WHEN** 通过 `call_tool("query", {"source": "ghost"})` 调用
- **THEN** 返回 TextContent JSON 必须含 `error` 字段，进程 MUST 不崩溃

#### Scenario: query 透传 fields 白名单

- **WHEN** `_handle_query({source, fields: ["_timestamp", "_message"]})` 调用
- **THEN** engine 收到的 `fields` 参数与传入一致，返回 entries 中每条记录仅含这两个键

#### Scenario: tail 透传 agent_source 快捷过滤

- **WHEN** `_handle_tail({source, count, agent_source})` 调用
- **THEN** engine 收到的 `field_filters` 含 `agent_source` 键，entries 仅包含匹配该 agent 的条目

#### Scenario: tail 透传 fields 白名单

- **WHEN** `_handle_tail({source, count, fields: ["_timestamp", "_message"]})` 调用
- **THEN** engine 收到的 `fields` 参数与传入一致，返回 entries 中每条记录仅含这两个键

#### Scenario: summary 透传 percentile_fields 与 bucket_interval

- **WHEN** `_handle_summary({source, percentile_fields: ["duration_ms"], bucket_interval: "1m"})` 调用
- **THEN** 返回 JSON 同时含 `percentiles.duration_ms` 与 `time_buckets` 数组

#### Scenario: summary correlation_id 透传

- **WHEN** `_handle_summary({source, correlation_id: "run-001"})` 调用
- **THEN** engine 收到的 `field_filters` 含 `correlation_id` 键，统计结果受其过滤

#### Scenario: cross_query 成功

- **WHEN** `_handle_cross_query({sources: [a, b], join_field: correlation_id})` 调用，且两源均存在共享 correlation_id 的条目
- **THEN** 返回 JSON 含非空 `entries`

#### Scenario: cross_query sources 少于 2

- **WHEN** `_handle_cross_query({sources: ["only-one"], join_field: "x"})` 调用
- **THEN** 直接返回 `{"error": "sources 至少需要 2 个日志源"}`，MUST 不抛异常

#### Scenario: cross_query 源名不存在

- **WHEN** 通过 `call_tool("cross_query", {"sources": ["ghost", "also-ghost"], "join_field": "x"})` 调用
- **THEN** 返回 TextContent JSON 必须含 `error` 字段
