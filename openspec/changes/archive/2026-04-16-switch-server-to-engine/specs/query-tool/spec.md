## ADDED Requirements

### Requirement: Query Entries via Engine

_handle_query SHALL 调用 engine.query_entries() 执行日志过滤，不再使用 reader.py 和 query.py。参数映射不变：source、level、message_pattern、field_filters、since、until、limit（默认 50，最大 500）。返回结构不变：`{"total_matched": <int>, "entries": [...]}`，entries 按 _timestamp 升序排列。

#### Scenario: 调用 engine.query_entries 执行过滤

- **WHEN** 客户端调用 query 工具并传入合法的 source 和过滤参数
- **THEN** server 调用 engine.query_entries()，返回 `{"total_matched": N, "entries": [...]}`

#### Scenario: field_filters 语法兼容

- **WHEN** field_filters 中包含 ~pattern、>=N 或 !value 语法
- **THEN** engine 将其正确转换为参数化 SQL，结果与原 query.py 行为一致
