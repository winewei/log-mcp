## 1. server.py schema
- [x] 1.1 新增 cross_query tool schema（sources: string[], join_field: string, level: string, since: string, limit: integer）
- [x] 1.2 新增 _handle_cross_query handler 并注册到路由表

## 2. engine.py 实现
- [x] 2.1 新增 cross_query() 函数签名
- [x] 2.2 为每个 source 构造 CTE（read_json_auto + 归一化 + 基础过滤）
- [x] 2.3 CTE 间通过 INNER JOIN ON join_field 关联
- [x] 2.4 结果按 _timestamp 排序 + LIMIT
- [x] 2.5 每条记录附带 _source 标识来源

## 3. 安全
- [x] 3.1 join_field 列名白名单校验
- [x] 3.2 所有过滤条件参数化查询
