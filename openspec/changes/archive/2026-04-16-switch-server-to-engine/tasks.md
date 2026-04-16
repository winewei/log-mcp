## 1. 修改 server.py
- [x] 1.1 移除 `from .reader import ...` 和 `from .query import ...` 的 import
- [x] 1.2 添加 `from .engine import query_entries, tail_entries, summarize_entries`
- [x] 1.3 重写 _handle_query：调用 engine.query_entries() 替代 reader+query 调用链
- [x] 1.4 重写 _handle_tail：调用 engine.tail_entries() 替代启发式 read_reverse 逻辑
- [x] 1.5 重写 _handle_summary：调用 engine.summarize_entries() 替代 reader+query+summarize 调用链

## 2. 删除旧模块
- [x] 2.1 删除 log_mcp/reader.py
- [x] 2.2 删除 log_mcp/query.py

## 3. 回归验证
- [x] 3.1 验证 query 工具参数与返回结构与迁移前一致
- [x] 3.2 验证 tail 工具返回精确 count 条
- [x] 3.3 验证 summary 工具返回结构与迁移前一致
- [x] 3.4 验证 field_filters 各语法（~、>=、!）正常工作
