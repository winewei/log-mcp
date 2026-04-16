# MCP Tool Handlers Spec

## ADDED Requirements

### Requirement: Tool Schema Exposure
`list_tools` MUST 返回恰好 7 个 `Tool` 实例，涵盖 `list_sources`、`query`、`tail`、`summary`、`register_source`、`unregister_source`、`cross_query`，每个 Tool 的 `inputSchema` MUST 是合法的 JSON Schema 并声明正确的必填字段，以便 MCP 客户端据此构造请求。

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

### Requirement: File Status Introspection
`_file_status(path)` MUST 根据文件系统实际状态返回稳定字典 `{status, file_size_bytes, last_modified}`，便于 `list_sources` 向 Agent 暴露可诊断的源状态。

#### Scenario: 文件存在且非空

- **WHEN** 路径指向真实存在且 `size>0` 的文件
- **THEN** 返回 `status == "ok"`、`file_size_bytes > 0`、`last_modified` 为带时区的 ISO 8601 字符串

#### Scenario: 文件存在但为空

- **WHEN** 路径指向存在但 `size==0` 的文件
- **THEN** 返回 `status == "empty"`、`file_size_bytes == 0`、`last_modified` 非空

#### Scenario: 文件不存在

- **WHEN** 路径指向不存在的文件
- **THEN** 返回 `status == "missing"`、`file_size_bytes == 0`、`last_modified is None`

#### Scenario: 路径是目录

- **WHEN** 路径指向目录
- **THEN** 函数 MUST 不抛异常并返回结构化字典（status 基于 `stat` 的 size 计算）

#### Scenario: 无权限读取

- **WHEN** 文件存在但当前进程对其父目录无读权限或文件 `chmod 000`
- **THEN** 函数 MUST 能被测试稳定调用并返回字典，测试 teardown 必须恢复权限避免副作用

### Requirement: Source Lifecycle Handlers
`_handle_list_sources`、`_handle_register_source`、`_handle_unregister_source` MUST 基于模块级 `registry` 单例操作，并将结果编码为 `TextContent(type="text")`；非法输入经 `call_tool` 包装后 MUST 以 JSON `{"error": ...}` 形式返回而不是向上抛。

#### Scenario: 列出空 registry

- **WHEN** registry 无任何源，调用 `_handle_list_sources({})`
- **THEN** 返回单个 TextContent，其 `text` 反序列化后为 `[]`

#### Scenario: 列出多源

- **WHEN** registry 已注册 2 个源并调用 `_handle_list_sources({})`
- **THEN** 返回列表含两个字典，每个字典 MUST 同时包含 `name/description/path/format` 与 `status/file_size_bytes/last_modified`

#### Scenario: 注册新源成功

- **WHEN** `_handle_register_source({name, description, path, format=jsonl})` 调用
- **THEN** 返回 `{"status": "registered", "name": <name>}`，且 `registry.get(name)` 能检索到

#### Scenario: 注册参数非法被 call_tool 捕获

- **WHEN** 通过 `call_tool("register_source", {...format="invalid"})` 调用
- **THEN** 返回的 TextContent JSON 必须含 `error` 字段（由顶层异常捕获包装），不能向上抛 `ValueError`

#### Scenario: persist=True 写回 YAML

- **WHEN** registry 绑定了 `config_path` 且以 `persist=True` 注册源
- **THEN** 对应 `sources.yaml` 被重写，`load_config` 再次读取时能看到该源

#### Scenario: 注销存在的源

- **WHEN** `_handle_unregister_source({name})` 针对已存在源调用
- **THEN** 返回 `{"status": "unregistered", "name": <name>}`，后续 `registry.get(name)` MUST 抛 `KeyError`

#### Scenario: 注销不存在的源由 call_tool 包装

- **WHEN** 通过 `call_tool("unregister_source", {"name": "ghost"})` 调用
- **THEN** 返回的 TextContent JSON 必须含 `error` 字段

### Requirement: Query Handlers
`_handle_query`、`_handle_tail`、`_handle_summary`、`_handle_cross_query` MUST 将参数透传给 engine 层并序列化结果为 TextContent；源不存在或参数非法经 `call_tool` 包装后 MUST 返回错误 JSON 而非抛出。

#### Scenario: query 透传全部过滤参数

- **WHEN** `_handle_query({source, level, message_pattern, field_filters, since, until, limit, offset})` 调用
- **THEN** 返回 TextContent，其 JSON 含 `total_matched` 与 `entries` 结构，且受过滤条件影响

#### Scenario: query limit 被截断至 500

- **WHEN** `_handle_query({source, limit: 1000})` 调用
- **THEN** 传递给 engine 的 `limit` MUST 被截断为 500

#### Scenario: query 源不存在

- **WHEN** 通过 `call_tool("query", {"source": "ghost"})` 调用
- **THEN** 返回 TextContent JSON 必须含 `error` 字段，进程 MUST 不崩溃

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

#### Scenario: cross_query sources 少于 2

- **WHEN** `_handle_cross_query({sources: ["only-one"], join_field: "x"})` 调用
- **THEN** 直接返回 `{"error": "sources 至少需要 2 个日志源"}`，MUST 不抛异常

#### Scenario: cross_query 源名不存在

- **WHEN** 通过 `call_tool("cross_query", {"sources": ["ghost", "also-ghost"], "join_field": "x"})` 调用
- **THEN** 返回 TextContent JSON 必须含 `error` 字段

### Requirement: Server Startup
模块级 `server` 单例 MUST 在导入时完成 7 个 tool 的注册；`run_server(config_path)` MUST 在 `config_path` 非空时加载配置，为空时以纯动态模式启动，且 MCP `call_tool` 对未知名称 MUST 返回错误而非直接抛 `ValueError`。

#### Scenario: 模块导入即注册 7 个 tool

- **WHEN** 测试直接调用 `await list_tools()`（来自 `log_mcp.server`）
- **THEN** 返回列表长度 MUST 为 7，证明 `@server.list_tools()` 装饰器在导入时已生效

#### Scenario: 未知 tool 名称抛 ValueError

- **WHEN** 调用 `call_tool("nonexistent_tool", {})`
- **THEN** MUST 抛出 `ValueError`，错误消息含 "未知 tool" 与请求的 tool 名，由 MCP 框架层统一转译为协议错误响应

#### Scenario: run_server 无配置路径启动

- **WHEN** 调用 `run_server(config_path=None)` 并 mock `stdio_server` / `server.run`
- **THEN** MUST 记录"纯动态注册模式"日志并进入 stdio 循环，不加载任何 YAML
