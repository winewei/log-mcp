# summary-tool Specification

## Purpose
TBD - created by archiving change switch-server-to-engine. Update Purpose after archive.
## Requirements
### Requirement: Summarize Entries via Engine

_handle_summary SHALL 调用 engine.summarize_entries() 执行聚合统计，不再使用 reader.py 和 query.py 的调用链。参数映射不变：source、since（默认 5m）、agent_source、correlation_id、group_by。返回结构不变：包含 time_range、total、level_counts、top_messages，可选 groups。

#### Scenario: 调用 engine.summarize_entries 执行聚合

- **WHEN** 客户端调用 summary 工具并传入合法的 source 和时间窗口
- **THEN** server 调用 engine.summarize_entries()，返回包含 time_range、total、level_counts、top_messages 的聚合结果

#### Scenario: group_by 分组聚合

- **WHEN** 调用 summary 工具并传入 group_by 参数
- **THEN** 返回结果中包含 groups 字段，按指定维度分组统计 total 和 errors

### Requirement: Percentile Fields Parameter

summary 工具 SHALL 接受可选参数 percentile_fields（string[]），指定需要计算分位数统计的数值字段列表。当该参数存在且非空时，MUST 对每个字段使用 DuckDB approx_quantile 函数计算 p50、p95、p99。

#### Scenario: 传入单个数值字段

- **WHEN** 调用 summary 工具时传入 percentile_fields: ["duration_ms"]
- **THEN** 返回结构包含 percentiles.duration_ms 对象，含 p50、p95、p99 三个数值键

#### Scenario: 省略 percentile_fields 参数

- **WHEN** 调用 summary 工具时不传 percentile_fields 参数
- **THEN** 返回结构中不包含 percentiles 字段

### Requirement: Bucket Interval Parameter

summary 工具 SHALL 接受可选参数 bucket_interval（string），枚举值为 1m、5m、1h，指定时间桶分析的粒度。当该参数存在时，MUST 使用 DuckDB time_bucket 函数按指定间隔聚合。

#### Scenario: 按 5 分钟分桶

- **WHEN** 调用 summary 工具时传入 bucket_interval: "5m"
- **THEN** 返回结构包含 time_buckets 数组，每项含 bucket（ISO 8601）、total、errors，按 bucket 升序

#### Scenario: 省略 bucket_interval 参数

- **WHEN** 调用 summary 工具时不传 bucket_interval 参数
- **THEN** 返回结构中不包含 time_buckets 字段

### Requirement: Percentiles Return Structure

percentiles 字段 SHALL 遵循结构：顶层键为字段名，值为含 p50、p95、p99 键的对象。

#### Scenario: 返回结构格式验证

- **WHEN** summary 工具返回包含 percentiles 字段的结果
- **THEN** 结构符合 {"field_name": {"p50": float, "p95": float, "p99": float}} 格式

### Requirement: Time Buckets Return Structure

time_buckets 字段 SHALL 为数组，每个元素包含 bucket（ISO 8601 字符串）、total（整数）、errors（整数），按 bucket 升序排列。

#### Scenario: 返回结构格式验证

- **WHEN** summary 工具返回包含 time_buckets 字段的结果
- **THEN** 每个元素符合 {"bucket": "ISO8601", "total": int, "errors": int} 格式，按时间升序

