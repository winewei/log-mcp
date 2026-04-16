## 1. Implementation
- [x] 1.1 server.py：query tool JSON Schema 新增 offset 参数（type: integer, default: 0, minimum: 0）
- [x] 1.2 server.py：_handle_query 提取 offset 传入 engine.query_entries()
- [x] 1.3 engine.py：query_entries() 签名新增 offset: int = 0
- [x] 1.4 engine.py：query SQL 在 LIMIT 后追加 OFFSET $offset
