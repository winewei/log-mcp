## 1. SQL 重构
- [ ] 1.1 改写 log_mcp/engine.py 中 cross_query 函数：CTE 增加 _source 常量列
- [ ] 1.2 INNER JOIN 替换为 UNION ALL BY NAME
- [ ] 1.3 ORDER BY _timestamp ASC NULLS LAST

## 2. 接口与默认值
- [ ] 2.1 server.py cross_query inputSchema 增加 fields: list[str] 可选参数
- [ ] 2.2 since 缺省值改为 "1h"
- [ ] 2.3 description 字段保持现状（由 rewrite-tool-descriptions-when-to-use 改写）

## 3. 错误处理
- [ ] 3.1 join_field 不在白名单时返回 join_field_not_allowed 结构化错误（依赖 add-structured-error-response）

## 4. 字段裁剪复用
- [ ] 4.1 cross_query 输出经过公共 _project_fields（依赖 add-field-projection-layer）

## 5. 测试
- [ ] 5.1 单 correlation_id 多源命中：行数 = 各源命中之和
- [ ] 5.2 每条记录含 _source 字段
- [ ] 5.3 字段不同的两个源 UNION 后缺失自动补 NULL
- [ ] 5.4 since 缺省按 1h
- [ ] 5.5 join_field 非白名单返回结构化错误
- [ ] 5.6 fields 白名单生效
