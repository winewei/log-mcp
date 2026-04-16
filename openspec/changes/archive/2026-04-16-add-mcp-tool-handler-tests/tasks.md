# Tasks

## 1. 共享 fixtures
- [x] 1.1 在 `tests/test_server_handlers.py` 中构造 `registry_with_sources` fixture：基于 `tmp_path` 写入 JSONL 日志文件，注册到独立 `SourceRegistry` 实例，并在测试期间替换 `log_mcp.server.registry`
- [x] 1.2 构造 `cross_sources_registry` fixture：包含两个共享 `correlation_id` 的 JSONL 源，供 `_handle_cross_query` 测试使用
- [x] 1.3 构造 `persist_registry` fixture：在 `tmp_path` 下生成空 `sources.yaml`，返回绑定该路径的 `SourceRegistry`，用于持久化场景

## 2. Tool Schema 校验
- [x] 2.1 断言 `list_tools()` 返回恰好 7 个 `Tool`，名称集合为 `{list_sources, query, tail, summary, register_source, unregister_source, cross_query}`
- [x] 2.2 用 `jsonschema.Draft202012Validator.check_schema` 校验每个 `inputSchema` 为合法 JSON Schema
- [x] 2.3 断言每个 tool 的 `required` 字段与文档一致（如 `query.required == ["source"]`、`cross_query.required == ["sources", "join_field"]`）
- [x] 2.4 断言 `cross_query.sources` 含 `minItems: 2` 约束

## 3. `_file_status` 多状态测试
- [x] 3.1 文件存在且非空：`status=ok`、`file_size_bytes>0`、`last_modified` 为 ISO 8601 字符串
- [x] 3.2 文件存在但为空：`status=empty`、`file_size_bytes==0`
- [x] 3.3 文件不存在：`status=missing`、`file_size_bytes==0`、`last_modified is None`
- [x] 3.4 路径是目录而非文件：验证返回字典结构不抛异常（记录实际契约）
- [x] 3.5 无权限读取（`chmod 000`）：验证当前契约行为，在 teardown 恢复权限

## 4. Source Lifecycle Handler 测试
- [x] 4.1 `_handle_list_sources` 空 registry：返回 `[]` 序列化为 `"[]"`
- [x] 4.2 `_handle_list_sources` 多源：结果含全部源名，每条记录包含 `name/description/path/format/status/file_size_bytes/last_modified`
- [x] 4.3 `_handle_register_source` 成功：注册后 `registry.list()` 可见该源
- [x] 4.4 `_handle_register_source` 参数非法：如 `format=invalid`，经 `call_tool` 包装后返回含 `error` 字段的 JSON 文本
- [x] 4.5 `_handle_register_source` `persist=True`：sources.yaml 被重写且可被 `load_config` 再次读出
- [x] 4.6 `_handle_unregister_source` 成功：注销后 `registry.get()` 抛 `KeyError`
- [x] 4.7 `_handle_unregister_source` 不存在的源：经 `call_tool` 包装后返回含 `error` 字段的 JSON

## 5. Query Handler 测试
- [x] 5.1 `_handle_query` 成功：透传 `level/message_pattern/field_filters/since/until/limit/offset`，返回 entries 结构
- [x] 5.2 `_handle_query` 源不存在：经 `call_tool` 路由后返回 `{"error": ...}` 文本（不抛出异常）
- [x] 5.3 `_handle_query` limit 截断：传入 1000 应被截断为 500
- [x] 5.4 `_handle_tail` 成功 + `agent_source` 快捷过滤：结果包含对应 agent 的条目
- [x] 5.5 `_handle_tail` 源不存在：返回错误 JSON
- [x] 5.6 `_handle_summary` 成功：返回 `total/level_counts/time_range/top_messages`
- [x] 5.7 `_handle_summary` 透传 `percentile_fields` 与 `bucket_interval`：结果含 `percentiles` 与 `time_buckets`
- [x] 5.8 `_handle_summary` `correlation_id` 透传至 field_filters 生效
- [x] 5.9 `_handle_cross_query` 成功：两源 JOIN 返回非空 entries
- [x] 5.10 `_handle_cross_query` `sources` 仅 1 个：直接返回 `{"error": "sources 至少需要 2 个日志源"}`
- [x] 5.11 `_handle_cross_query` 源名不存在：经 `call_tool` 包装后返回错误 JSON

## 6. `run_server` Smoke Test
- [x] 6.1 直接调用 `await list_tools()` 断言返回 7 个 tool（模块级 server 单例已注册）
- [x] 6.2 未知 tool 名称经 `call_tool` 调用时抛 `ValueError`（以实际契约为准；spec Scenario 已同步更新）
- [x] 6.3 覆盖 `run_server(config_path=None)` 的分支：mock `stdio_server` 与 `server.run` 后确认初始化路径可走通

## 7. 运行与验证
- [x] 7.1 `pytest tests/test_server_handlers.py -v` 全部通过
- [x] 7.2 `pytest` 全量通过，不影响现有 48 个 engine 测试
