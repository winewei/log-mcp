# Change: 新增 engine.py — DuckDB SQL 生成与执行层

## Why
engine.py 是替代 reader.py + query.py 的核心模块，封装 JSONL/text 读取 SQL 构造、过滤器到参数化 SQL WHERE 的映射、DuckDB 连接管理与执行，以及字段归一化。所有查询类工具将统一依赖此模块。

## What Changes
- 新增 log_mcp/engine.py，包含 discover_files()、_read_source_sql()、_build_where()、_execute()
- 实现 query_entries()、tail_entries()、summarize_entries() 三个面向 server.py 的公开接口
- 所有用户输入通过 DuckDB $N 参数化查询传入，防止 SQL 注入

## Impact
- Affected specs: new:duckdb-query-engine
- Affected code: log_mcp/engine.py（新增）
