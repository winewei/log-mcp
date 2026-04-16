## 1. 文件读取层
- [x] 1.1 实现 _read_source_sql()：JSONL 模式使用 read_json_auto，text 模式使用 read_csv 单列
- [x] 1.2 实现 discover_files()：从 reader.py 迁移轮转文件发现逻辑（glob 匹配）

## 2. 过滤层
- [x] 2.1 实现 _build_where()：level、message_pattern、since、until 基础过滤
- [x] 2.2 实现 _parse_filter_expr()：field_filters 5 种语法到参数化 SQL 的映射
- [x] 2.3 所有用户输入通过 $N 参数传入，验证无 SQL 拼接

## 3. 执行层
- [x] 3.1 实现 _execute()：:memory: 连接创建、SQL 执行、结果转 dict 列表
- [x] 3.2 可选：模块级连接复用优化（_get_conn 模式）

## 4. 公开接口
- [x] 4.1 实现 query_entries()：ORDER BY _timestamp ASC + LIMIT
- [x] 4.2 实现 tail_entries()：ORDER BY _timestamp DESC + LIMIT
- [x] 4.3 实现 summarize_entries()：基础统计 + top 消息 + 分组聚合
