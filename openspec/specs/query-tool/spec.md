# query-tool Specification

## Purpose
TBD - created by archiving change switch-server-to-engine. Update Purpose after archive.
## Requirements
### Requirement: Query Entries via Engine

_handle_query SHALL 调用 engine.query_entries() 执行日志过滤，不再使用 reader.py 和 query.py。参数映射不变：source、level、message_pattern、field_filters、since、until、limit（默认 50，最大 500）。返回结构不变：`{"total_matched": <int>, "entries": [...]}`，entries 按 _timestamp 升序排列。

#### Scenario: 调用 engine.query_entries 执行过滤

- **WHEN** 客户端调用 query 工具并传入合法的 source 和过滤参数
- **THEN** server 调用 engine.query_entries()，返回 `{"total_matched": N, "entries": [...]}`

#### Scenario: field_filters 语法兼容

- **WHEN** field_filters 中包含 ~pattern、>=N 或 !value 语法
- **THEN** engine 将其正确转换为参数化 SQL，结果与原 query.py 行为一致

### Requirement: Offset Parameter

query 工具 schema 中 SHALL 包含 offset 参数，类型为 integer，默认值为 0，最小值为 0，表示跳过结果集中前 N 条记录。

#### Scenario: offset 默认值为 0

- **WHEN** 调用 query 工具时未提供 offset 参数
- **THEN** offset 默认取 0，返回从第一条记录开始的结果

#### Scenario: offset 为负数时拒绝

- **WHEN** 调用 query 工具时传入 offset < 0
- **THEN** 工具返回参数验证错误，不执行查询

### Requirement: Pagination Behavior

engine.query_entries() 在生成 SQL 时 SHALL 将 LIMIT 与 OFFSET 组合使用，由 DuckDB 在引擎层执行分页。

#### Scenario: limit 与 offset 组合分页

- **WHEN** 调用 query 时传入 limit=20, offset=40
- **THEN** 返回按 _timestamp ASC 排序后第 41~60 条记录

#### Scenario: offset 超出结果集范围

- **WHEN** offset 大于满足过滤条件的总记录数
- **THEN** 返回空列表，不报错

