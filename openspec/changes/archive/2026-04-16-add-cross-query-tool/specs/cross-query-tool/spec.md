## ADDED Requirements

### Requirement: Sources Parameter

cross_query 工具 SHALL 接受必填参数 sources（string[]），指定参与关联的日志源名称列表，至少包含 2 个源。

#### Scenario: 传入 2 个源

- **WHEN** 调用 cross_query 时传入 sources: ["api-server", "client-log"]
- **THEN** 工具对两个源的日志执行 JOIN 关联查询

#### Scenario: 传入少于 2 个源

- **WHEN** 调用 cross_query 时传入 sources 包含少于 2 个元素
- **THEN** 工具返回参数验证错误

### Requirement: Join Field Parameter

cross_query 工具 SHALL 接受必填参数 join_field（string），指定用于关联的字段名。

#### Scenario: 通过 correlation_id 关联

- **WHEN** 调用 cross_query 时传入 join_field: "correlation_id"
- **THEN** 工具使用 INNER JOIN ON correlation_id 关联各源日志

### Requirement: Level Filter

cross_query 工具 SHALL 接受可选参数 level（string），过滤条件应用于所有参与源。

#### Scenario: 按 error 级别过滤

- **WHEN** 调用 cross_query 时传入 level: "error"
- **THEN** 每个源的 CTE 中包含 level='error' 过滤条件

### Requirement: Since Filter

cross_query 工具 SHALL 接受可选参数 since（string），指定时间范围起点。

#### Scenario: 指定时间范围

- **WHEN** 调用 cross_query 时传入 since: "2026-04-04T10:00:00Z"
- **THEN** 每个源的 CTE 中包含时间范围过滤

### Requirement: Limit Parameter

cross_query 工具 SHALL 接受可选参数 limit（integer），默认值为 50，限制返回条数。

#### Scenario: 默认返回 50 条

- **WHEN** 调用 cross_query 时未传 limit 参数
- **THEN** 最多返回 50 条关联结果

### Requirement: Return Structure

cross_query 工具 SHALL 返回按时间排序的合并条目，每条带 _source 字段标识来源。

#### Scenario: 返回结构包含 _source 标识

- **WHEN** cross_query 返回关联结果
- **THEN** 每条记录包含 _source 字段，值为对应的日志源名称

### Requirement: JOIN Behavior

cross_query 工具 SHALL 使用 INNER JOIN 关联各源，仅返回在所有源中均存在匹配 join_field 值的记录。

#### Scenario: INNER JOIN 语义

- **WHEN** source_a 有 correlation_id="abc" 但 source_b 中无该值
- **THEN** 该记录不出现在返回结果中
