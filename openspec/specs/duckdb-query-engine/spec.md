# duckdb-query-engine Specification

## Purpose
TBD - created by archiving change create-duckdb-engine. Update Purpose after archive.
## Requirements
### Requirement: JSONL File Reading

engine MUST 使用 DuckDB `read_json_auto` 读取 JSONL 格式日志文件，启用 `ignore_errors=true` 跳过解析失败行，启用 `filename=true` 附带来源文件名。

#### Scenario: 读取多个 JSONL 文件

- **WHEN** 传入多个 JSONL 文件路径
- **THEN** engine 使用 `read_json_auto` 合并读取所有文件，自动推断 schema

#### Scenario: 跳过格式错误的行

- **WHEN** JSONL 文件中存在非法 JSON 行
- **THEN** engine 跳过该行继续处理，不抛出异常

### Requirement: Text File Reading

engine MUST 使用 DuckDB `read_csv` 单列模式读取纯文本日志，列名为 `column0`，类型为 VARCHAR。

#### Scenario: 读取纯文本日志

- **WHEN** 日志源格式为 text
- **THEN** engine 使用 `read_csv(files, header=false, columns={'column0': 'VARCHAR'})` 读取，每行作为一条记录

### Requirement: Filter to SQL WHERE Mapping

engine MUST 将 field_filters 的 5 种语法映射为参数化 SQL WHERE 子句。

#### Scenario: 精确匹配

- **WHEN** field_filters 包含 `{"status": "200"}`
- **THEN** 生成 `status = $N`，参数值为 "200"

#### Scenario: 正则匹配

- **WHEN** field_filters 包含 `{"path": "~^/api/v1"}`
- **THEN** 生成 `regexp_matches(path, $N)`，参数值为 "^/api/v1"

#### Scenario: 数值比较

- **WHEN** field_filters 包含 `{"status": ">=400"}`
- **THEN** 生成 `CAST(status AS DOUBLE) >= $N`，参数值为 400

#### Scenario: 取反匹配

- **WHEN** field_filters 包含 `{"source": "!debug"}`
- **THEN** 生成 `source != $N OR source IS NULL`，参数值为 "debug"

### Requirement: Time Range Filtering

engine MUST 支持 since 和 until 参数，将归一化后的 `_timestamp` 字段转为 TIMESTAMPTZ 进行比较。

#### Scenario: 指定时间范围

- **WHEN** 传入 since 和 until 参数
- **THEN** 生成 `CAST(_timestamp AS TIMESTAMPTZ) >= $N AND CAST(_timestamp AS TIMESTAMPTZ) <= $M`

### Requirement: query_entries Interface

query_entries() MUST 返回按 `_timestamp` 升序排列的日志条目，支持 LIMIT 限制返回条数。

#### Scenario: 按时间升序查询

- **WHEN** 调用 query_entries() 并传入 limit=50
- **THEN** 返回按 _timestamp ASC 排序的前 50 条匹配记录

### Requirement: tail_entries Interface

tail_entries() MUST 返回按 `_timestamp` 降序排列的最新日志条目，通过 DuckDB 全扫描排序取 top-N，结果精确。

#### Scenario: 获取最新 N 条日志

- **WHEN** 调用 tail_entries() 并传入 count=20
- **THEN** 返回按 _timestamp DESC 排序的最新 20 条匹配记录，条数精确

### Requirement: summarize_entries Interface

summarize_entries() MUST 返回包含基础统计（total、level_counts、time_range）、top 消息和可选分组聚合的聚合结果。

#### Scenario: 基础聚合统计

- **WHEN** 调用 summarize_entries()
- **THEN** 返回 total、earliest/latest 时间戳、各 level 计数、top 10 消息

#### Scenario: 分组聚合

- **WHEN** 调用 summarize_entries() 并传入 group_by 参数
- **THEN** 返回按指定字段分组的 total 和 errors 统计

### Requirement: Parameterized Queries

engine 中所有用户输入 MUST 通过 DuckDB 参数化查询（$1, $2, ...）传入，禁止字符串拼接；跨源 SQL 构造时各 CTE 的参数序号 MUST 重映射为全局连续编号，避免冲突。

#### Scenario: SQL 注入防护

- **WHEN** 用户输入包含 SQL 特殊字符（如 `'; DROP TABLE --`）
- **THEN** 输入作为参数值传入，不影响 SQL 结构

#### Scenario: 跨源 CTE 参数序号重映射

- **WHEN** cross_query 为 N 个源构造 N 个 CTE，每个 CTE 通过 _build_where 生成局部 $1/$2 占位符
- **THEN** engine 在拼接 CTE 时将各 CTE 的占位符按累计偏移重写为全局 $K，保证最终 SQL 中参数序号唯一连续

### Requirement: Connection Management

engine MUST 使用 DuckDB `:memory:` 模式，不创建磁盘数据库文件。

#### Scenario: 内存模式连接

- **WHEN** engine 执行任意查询
- **THEN** 使用 `duckdb.connect(":memory:")` 创建连接，不产生磁盘文件

### Requirement: File Discovery

engine MUST 提供 discover_files() 函数，根据日志源配置的路径和轮转规则发现所有匹配的日志文件。

#### Scenario: glob 模式文件发现

- **WHEN** 日志源配置了 glob 路径模式
- **THEN** discover_files() 返回所有匹配的文件路径列表

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

