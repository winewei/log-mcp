# Change: server.py 切换到 engine.py 并删除旧模块

## Why
将 server.py 中 query/tail/summary 三个 handler 的调用链从 reader+query 切换到 engine，完成核心路径替换，并清除不再需要的 reader.py 和 query.py。

## What Changes
- server.py 中 _handle_query、_handle_tail、_handle_summary 改为调用 engine.py 的公开接口
- 移除 server.py 对 reader.py 和 query.py 的 import
- 删除 log_mcp/reader.py 和 log_mcp/query.py

## Impact
- Affected specs: modify:query-tool, modify:tail-tool, modify:summary-tool
- Affected code: log_mcp/server.py（修改）, log_mcp/reader.py（删除）, log_mcp/query.py（删除）
