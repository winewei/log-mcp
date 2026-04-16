# Change: query 工具新增 offset 分页参数

## Why
当前 query 仅支持 limit 截断，无法定位中间段结果。新增 offset 参数配合 limit 实现标准游标分页，由 DuckDB LIMIT+OFFSET 在引擎层执行。

## What Changes
- server.py 中 query tool schema 新增 offset 参数（integer，默认 0）
- _handle_query 将 offset 传入 engine.query_entries()
- engine.py 的 query SQL 添加 OFFSET $offset 子句

## Impact
- Affected specs: modify:query-tool
- Affected code: log_mcp/server.py, log_mcp/engine.py
