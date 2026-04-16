# Change: 新增 cross_query 跨源关联查询工具

## Why
跨服务/跨端调用链排障需要跨多个日志源通过 correlation_id 等共享字段进行 JOIN 关联查询，当前架构不支持。利用 DuckDB 原生 JOIN 能力将跨源关联提升为一等操作。

## What Changes
- server.py 新增 cross_query tool schema（sources: string[], join_field: string, level, since, limit）
- engine.py 新增 cross_query() 函数，为每个 source 构造 CTE 后通过 JOIN ON join_field 关联
- server.py 新增 _handle_cross_query handler 并注册到路由表

## Impact
- Affected specs: new:cross-query-tool
- Affected code: log_mcp/server.py, log_mcp/engine.py
