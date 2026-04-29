# query-tool Specification Delta

## MODIFIED Requirements

### Requirement: Query Entries via Engine

_handle_query SHALL 调用 engine.query_entries() 执行日志过滤，不再使用 reader.py 和 query.py。参数映射不变：source、level、message_pattern、field_filters、since、until、limit（默认 50，最大 500）。返回结构不变：`{"total_matched": <int>, "entries": [...]}`，entries 按 _timestamp 升序排列。entries 中每条记录在序列化前 SHALL 经过公共裁剪层 `_project_fields` 处理：未传 fields 时对单字段值序列化超过 4KB 的字段替换为 `<truncated:<size>>` 占位符，归一化字段 _timestamp/_level/_message/_source 不参与截断。

#### Scenario: 调用 engine.query_entries 执行过滤

- **WHEN** 客户端调用 query 工具并传入合法的 source 和过滤参数
- **THEN** server 调用 engine.query_entries()，返回 `{"total_matched": N, "entries": [...]}`

#### Scenario: field_filters 语法兼容

- **WHEN** field_filters 中包含 ~pattern、>=N 或 !value 语法
- **THEN** engine 将其正确转换为参数化 SQL，结果与原 query.py 行为一致

#### Scenario: 默认裁剪大字段

- **WHEN** 未传 fields 且 entries 中存在单字段值序列化后大于 4KB（例如 100KB body）
- **THEN** 该字段在返回 entry 中被替换为 `<truncated:100.0KB>` 字符串，其它小字段原样返回

#### Scenario: 归一化字段不被截断

- **WHEN** entries 中 _timestamp/_level/_message/_source 字段值理论上超过 4KB
- **THEN** 这四个归一化字段在返回 entry 中保留原值，不被替换为占位符

## ADDED Requirements

### Requirement: Fields 白名单参数

query 工具 SHALL 支持可选参数 `fields: list[str]`。fields 传入时返回 entries 仅包含 fields 列表中的字段（归一化字段需显式列入），fields 未列出的字段一律省略；fields 列出的字段 SHALL 不参与大字段截断，原值返回；fields 中含 entries 实际不存在的字段时该字段以 NULL 占位返回，不报错。

#### Scenario: 白名单仅返回指定字段

- **WHEN** 调用 query 工具传入 `fields=["_timestamp", "_message"]`
- **THEN** 返回的每条 entry 仅包含 `_timestamp` 与 `_message` 两个键，其它字段（含 _level/_source 等归一化字段）均不出现

#### Scenario: 白名单内大字段不被截断

- **WHEN** 调用 query 工具传入 `fields=["body"]` 且 body 字段值大小为 100KB
- **THEN** 返回 entry 中 body 字段保留原始 100KB 值，不被替换为占位符

#### Scenario: 白名单包含不存在字段

- **WHEN** 调用 query 工具传入 `fields=["nonexistent"]` 且 entries 中无该字段
- **THEN** 返回 entry 中 `nonexistent` 键存在且值为 `null`，处理流程不抛异常
