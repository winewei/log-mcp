## ADDED Requirements

### Requirement: Summarize Entries via Engine

_handle_summary SHALL 调用 engine.summarize_entries() 执行聚合统计，不再使用 reader.py 和 query.py 的调用链。参数映射不变：source、since（默认 5m）、agent_source、correlation_id、group_by。返回结构不变：包含 time_range、total、level_counts、top_messages，可选 groups。

#### Scenario: 调用 engine.summarize_entries 执行聚合

- **WHEN** 客户端调用 summary 工具并传入合法的 source 和时间窗口
- **THEN** server 调用 engine.summarize_entries()，返回包含 time_range、total、level_counts、top_messages 的聚合结果

#### Scenario: group_by 分组聚合

- **WHEN** 调用 summary 工具并传入 group_by 参数
- **THEN** 返回结果中包含 groups 字段，按指定维度分组统计 total 和 errors
