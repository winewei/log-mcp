# Change: cross_query 由 INNER JOIN 重构为 UNION ALL 时间线

## Why
现有 INNER JOIN 导致行数笛卡尔积膨胀且仅保留 s0 字段，与跨源调用链回放语义不符；改为 UNION ALL BY NAME 按时间线合并。

## What Changes
- SQL 由 INNER JOIN 改为 UNION ALL BY NAME 按 _timestamp 排序，对应 cross-query-tool spec 中 JOIN Behavior、Return Structure requirement 同步 MODIFIED 由 INNER JOIN 语义改写为 UNION ALL timeline 语义
- 每条记录补 _source 字段标识来源，缺失字段自动补 NULL
- since 缺省值改为 1h 避免无界扫描
- join_field 白名单拒绝时返回 join_field_not_allowed 结构化错误
- 明确不引入 mode 参数，工具名保持 cross_query 兼容现有调用
- cross_query 输出复用公共字段裁剪层（默认 4KB 截断 + 可选 fields 白名单）

## Impact
- Affected specs: modify:cross-query-tool, modify:duckdb-query-engine
- Affected code: log_mcp/engine.py（cross_query 函数 SQL 构造）, log_mcp/server.py（cross_query inputSchema 加 fields、since 默认值）
