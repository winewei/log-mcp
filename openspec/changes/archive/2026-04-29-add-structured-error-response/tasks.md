## 1. 错误 Schema 定义
- [x] 1.1 在 log_mcp/server.py 中定义错误响应构造函数 `_make_error(code, detail, suggestion, hints)`
- [x] 1.2 定义 error_code 常量集合：`source_not_found` / `field_not_found` / `time_parse_error` / `join_field_not_allowed` / `internal_error`
- [x] 1.3 约束 `suggestion` 为单句可执行动作；`hints` 为结构化字典

## 2. 异常映射
- [x] 2.1 `call_tool` 顶层捕获 `KeyError`（registry.get 未命中）映射为 `source_not_found`，hints 含 `available_sources`
- [x] 2.2 捕获 DuckDB BinderException / 字段引用失败映射为 `field_not_found`，hints 含候选字段名（最多 3 个近似匹配）
- [x] 2.3 捕获 `_parse_time` 抛出的 `ValueError` 映射为 `time_parse_error`，hints 含合法示例
- [x] 2.4 `cross_query` 白名单拒绝时映射为 `join_field_not_allowed`，hints 含全部白名单字段
- [x] 2.5 兜底其他未预期异常映射为 `internal_error`，hints 含异常类型
- [x] 2.6 移除现有 `{"error": ...}` 旧返回路径，统一走 `_make_error`

## 3. 测试
- [x] 3.1 测试 `query(source="ghost")` 返回 `error_code=source_not_found` 且 hints.available_sources 非空
- [x] 3.2 测试 `query(field_filters={"foo": "bar"})` 字段不存在时返回 `error_code=field_not_found` 且 hints 含候选
- [x] 3.3 测试 `query(since="yesterday")` 返回 `error_code=time_parse_error` 且 hints 含示例
- [x] 3.4 测试 `cross_query(join_field="email")` 返回 `error_code=join_field_not_allowed` 且 hints 含白名单
- [x] 3.5 测试未预期异常返回 `error_code=internal_error` 且包含异常类型
- [x] 3.6 验证旧 `{"error": ...}` 字段已不存在于任何错误响应中
