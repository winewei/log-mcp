## ADDED Requirements

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

engine 中所有用户输入 MUST 通过 DuckDB 参数化查询（$1, $2, ...）传入，禁止字符串拼接。

#### Scenario: SQL 注入防护

- **WHEN** 用户输入包含 SQL 特殊字符（如 `'; DROP TABLE --`）
- **THEN** 输入作为参数值传入，不影响 SQL 结构

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
