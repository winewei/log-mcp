# cross-query-tool Spec Delta

## MODIFIED Requirements

### Requirement: JOIN Behavior

cross_query 工具 SHALL 使用 UNION ALL BY NAME 按时间线合并各源记录，不执行关系代数 JOIN，每个源命中的所有记录均出现在结果中（不做笛卡尔积），缺失字段自动补 NULL。

#### Scenario: 多源记录合并为时间线

- **WHEN** source_a 在某 join_field 值上命中 3 条、source_b 命中 5 条
- **THEN** 返回 8 条按 _timestamp 升序排列的记录，且不发生笛卡尔积膨胀

#### Scenario: 单源命中其他源未命中

- **WHEN** source_a 有 correlation_id="abc" 共 2 条但 source_b 中无该值
- **THEN** 返回 2 条 source_a 的记录（不像 INNER JOIN 那样被过滤掉）

#### Scenario: 字段不对齐自动补 NULL

- **WHEN** source_a 含字段 screen 但 source_b 不含、source_b 含字段 path 但 source_a 不含
- **THEN** UNION 后每条 source_a 记录的 path 为 NULL，每条 source_b 记录的 screen 为 NULL，不抛出列不存在错误

### Requirement: Return Structure

cross_query 工具 SHALL 返回按 _timestamp 升序合并的全部源条目，每条带 _source 字段标识来源，每条记录保留其原源的全部字段，且按 NULLS LAST 处理无时间戳记录。

#### Scenario: 每条记录均带 _source

- **WHEN** cross_query 返回多源合并结果
- **THEN** 每条 entry 含 _source 字段，值为对应日志源名称

#### Scenario: 保留各源原生字段

- **WHEN** source_a 含 _message="frontend click"、source_b 含 _message="backend 500"
- **THEN** 返回结果中两个源的 _message 字段均保留原值，未被裁剪为 s0.* 形式

#### Scenario: 时间戳缺失记录排在末尾

- **WHEN** 部分记录 _timestamp 为 NULL（如 text 格式源）
- **THEN** 这些记录按 NULLS LAST 排在结果末尾，不影响其他记录顺序

## ADDED Requirements

### Requirement: Default Since Window

cross_query 工具 SHALL 在调用方未传 since 参数时使用默认值 "1h"，避免对所有源进行无界全表扫描。

#### Scenario: since 缺省按 1h 处理

- **WHEN** 调用 cross_query 时未传 since 参数
- **THEN** 各源 CTE 内自动追加 `_timestamp >= now()-1h` 过滤

#### Scenario: 显式 since 覆盖默认值

- **WHEN** 调用 cross_query 时传入 since="1d"
- **THEN** 各源 CTE 内追加 1 天窗口过滤而非 1h

### Requirement: Fields Projection Parameter

cross_query 工具 SHALL 接受可选参数 fields（list[string]），仅返回白名单字段；未传时复用公共字段裁剪层默认行为（4KB 单字段截断 + 永远保留 _timestamp/_level/_message/_source）。

#### Scenario: fields 白名单生效

- **WHEN** 调用 cross_query 时传入 fields=["_timestamp", "_source", "_message", "correlation_id"]
- **THEN** 返回每条 entry 仅含这 4 个字段，其他字段全部省略

#### Scenario: fields 包含不存在字段

- **WHEN** 调用 cross_query 时传入 fields=["nonexistent"]
- **THEN** 返回每条 entry 中 nonexistent 为 NULL，不抛出错误

#### Scenario: 未传 fields 时大字段被截断

- **WHEN** 未传 fields 且某记录 body 字段序列化超过 4KB
- **THEN** 该字段在输出中替换为 `<truncated:...>` 占位符，原值不返回

### Requirement: Join Field Whitelist Structured Error

cross_query 工具 SHALL 在 join_field 不在白名单时返回结构化错误 error_code=join_field_not_allowed，hints 含全部白名单字段。

#### Scenario: 非白名单 join_field 触发结构化错误

- **WHEN** 调用 cross_query 时传入 join_field="email"（不在白名单）
- **THEN** 返回 `{"error_code": "join_field_not_allowed", "detail": "...", "suggestion": "...", "hints": {"allowed": ["correlation_id", "request_id", ...]}}`

#### Scenario: 白名单 join_field 正常通过

- **WHEN** 调用 cross_query 时传入 join_field="correlation_id"
- **THEN** 不返回错误，按 UNION ALL 时间线语义执行查询

### Requirement: No Mode Parameter

cross_query 工具 SHALL NOT 引入 mode 参数；工具名保持 cross_query 不变以兼容既有调用方。

#### Scenario: 仅有 timeline 语义

- **WHEN** 调用方传入任何参数组合
- **THEN** 工具始终按 UNION ALL 时间线语义执行，不存在切换为关系代数 JOIN 的开关
