# tail-tool Specification

## Purpose
TBD - created by archiving change switch-server-to-engine. Update Purpose after archive.
## Requirements
### Requirement: Tail Entries via Engine

_handle_tail SHALL 调用 engine.tail_entries() 获取最新日志，不再使用启发式 read_reverse(count * 2) 策略。结果精确：无论过滤条件命中率多低，返回条数精确等于 count（或实际可用条数，若日志总量不足）。entries 中每条记录在序列化前 SHALL 经过公共裁剪层 `_project_fields` 处理：未传 fields 时对单字段值序列化超过 4KB 的字段替换为 `<truncated:<size>>` 占位符，归一化字段 _timestamp/_level/_message/_source 不参与截断。

#### Scenario: 精确返回 count 条

- **WHEN** 过滤条件命中率较低（例如仅 10% 的行满足 level=error）
- **THEN** engine 通过 DuckDB 全扫描排序取 top-N，精确返回 count 条

#### Scenario: count 默认值与上限约束

- **WHEN** 调用 tail 工具未传 count 参数
- **THEN** 实际 count 取 20；若传入超过 200 的值，则截断为 200

#### Scenario: 默认裁剪大字段

- **WHEN** 未传 fields 且 tail 返回的 entries 中存在单字段值序列化后大于 4KB（例如 100KB body）
- **THEN** 该字段在返回 entry 中被替换为 `<truncated:100.0KB>` 字符串，其它小字段原样返回

#### Scenario: 归一化字段不被截断

- **WHEN** tail 返回的 entries 中 _timestamp/_level/_message/_source 字段值理论上超过 4KB
- **THEN** 这四个归一化字段在返回 entry 中保留原值，不被替换为占位符

### Requirement: Fields 白名单参数

tail 工具 SHALL 支持可选参数 `fields: list[str]`。fields 传入时返回 entries 仅包含 fields 列表中的字段（归一化字段需显式列入），fields 未列出的字段一律省略；fields 列出的字段 SHALL 不参与大字段截断，原值返回；fields 中含 entries 实际不存在的字段时该字段以 NULL 占位返回，不报错。

#### Scenario: 白名单仅返回指定字段

- **WHEN** 调用 tail 工具传入 `fields=["_timestamp", "_message"]`
- **THEN** 返回的每条 entry 仅包含 `_timestamp` 与 `_message` 两个键，其它字段（含 _level/_source 等归一化字段）均不出现

#### Scenario: 白名单内大字段不被截断

- **WHEN** 调用 tail 工具传入 `fields=["body"]` 且 body 字段值大小为 100KB
- **THEN** 返回 entry 中 body 字段保留原始 100KB 值，不被替换为占位符

#### Scenario: 白名单包含不存在字段

- **WHEN** 调用 tail 工具传入 `fields=["nonexistent"]` 且 entries 中无该字段
- **THEN** 返回 entry 中 `nonexistent` 键存在且值为 `null`，处理流程不抛异常

