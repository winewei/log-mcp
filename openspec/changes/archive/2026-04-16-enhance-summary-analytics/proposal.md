# Change: summary 工具新增分位数统计与时间桶分析

## Why
当前 summary 仅支持 count + top-10 聚合，无法提供性能分位数和趋势分析。利用 DuckDB 分析函数扩展 percentile_fields 和 bucket_interval，增强 Agent 对服务健康状况的判断能力。

## What Changes
- server.py 中 summary tool schema 新增 percentile_fields（string[]）和 bucket_interval（string）参数
- engine.py summarize_entries() 新增 percentile SQL（approx_quantile）和 time_bucket SQL
- 返回结构新增 percentiles 和 time_buckets 字段

## Impact
- Affected specs: modify:summary-tool
- Affected code: log_mcp/server.py, log_mcp/engine.py
