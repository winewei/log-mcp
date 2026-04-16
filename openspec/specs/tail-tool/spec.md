# tail-tool Specification

## Purpose
TBD - created by archiving change switch-server-to-engine. Update Purpose after archive.
## Requirements
### Requirement: Tail Entries via Engine

_handle_tail SHALL 调用 engine.tail_entries() 获取最新日志，不再使用启发式 read_reverse(count * 2) 策略。结果精确：无论过滤条件命中率多低，返回条数精确等于 count（或实际可用条数，若日志总量不足）。

#### Scenario: 精确返回 count 条

- **WHEN** 过滤条件命中率较低（例如仅 10% 的行满足 level=error）
- **THEN** engine 通过 DuckDB 全扫描排序取 top-N，精确返回 count 条

#### Scenario: count 默认值与上限约束

- **WHEN** 调用 tail 工具未传 count 参数
- **THEN** 实际 count 取 20；若传入超过 200 的值，则截断为 200

