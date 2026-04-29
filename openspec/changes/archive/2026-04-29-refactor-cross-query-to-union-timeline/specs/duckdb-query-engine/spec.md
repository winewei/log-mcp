# duckdb-query-engine Spec Delta

## MODIFIED Requirements

### Requirement: Parameterized Queries

engine 中所有用户输入 MUST 通过 DuckDB 参数化查询（$1, $2, ...）传入，禁止字符串拼接；跨源 SQL 构造时各 CTE 的参数序号 MUST 重映射为全局连续编号，避免冲突。

#### Scenario: SQL 注入防护

- **WHEN** 用户输入包含 SQL 特殊字符（如 `'; DROP TABLE --`）
- **THEN** 输入作为参数值传入，不影响 SQL 结构

#### Scenario: 跨源 CTE 参数序号重映射

- **WHEN** cross_query 为 N 个源构造 N 个 CTE，每个 CTE 通过 _build_where 生成局部 $1/$2 占位符
- **THEN** engine 在拼接 CTE 时将各 CTE 的占位符按累计偏移重写为全局 $K，保证最终 SQL 中参数序号唯一连续

## ADDED Requirements

### Requirement: Cross-Source SQL Construction

engine MUST 通过 UNION ALL BY NAME 而非 INNER JOIN 构造跨源 SQL：为每个源生成独立 CTE（含归一化 SELECT 与 _source 常量列），最终用 UNION ALL BY NAME 合并、按 _timestamp ASC NULLS LAST 排序、应用 LIMIT。

#### Scenario: 多源 CTE 通过 UNION ALL BY NAME 合并

- **WHEN** cross_query 接收 2 个及以上源
- **THEN** 生成 SQL 形如 `WITH s0 AS (...), s1 AS (...) SELECT * FROM s0 UNION ALL BY NAME SELECT * FROM s1 ORDER BY _timestamp ASC NULLS LAST LIMIT ?`，不含 INNER JOIN 关键字

#### Scenario: 各 CTE 携带 _source 常量列

- **WHEN** engine 为单个源生成 CTE
- **THEN** CTE 的 SELECT 表达式包含 `'<source_name>' AS _source`，确保 UNION 后每行可追溯来源

#### Scenario: 列不对齐由 UNION ALL BY NAME 自动处理

- **WHEN** 两个源 schema 不一致（一个有 path 字段、另一个没有）
- **THEN** UNION ALL BY NAME 按列名对齐合并，缺失列自动补 NULL，不报 binder 错误

### Requirement: Cross-Source Default Time Window

engine MUST 在 cross_query 调用方未传 since 时使用 "1h" 作为默认时间窗口，应用于全部参与源的 CTE WHERE 子句。

#### Scenario: cross_query 默认 1h 窗口

- **WHEN** cross_query 未传 since 参数
- **THEN** 每个源的 CTE 中均追加 `CAST(_timestamp AS TIMESTAMPTZ) >= <now-1h>` 过滤，避免无界扫描

### Requirement: Cross-Source Join Field Whitelist Preserved

engine MUST 在 cross_query 中保持 join_field 白名单（_ALLOWED_JOIN_FIELDS）校验不变，命中白名单外字段时短路返回结构化错误，不进入 SQL 构造阶段。

#### Scenario: 非白名单字段短路拒绝

- **WHEN** cross_query 收到 join_field="email"
- **THEN** engine 在 SQL 构造前返回结构化错误，不生成任何参数化 SQL，不执行 DuckDB 调用
