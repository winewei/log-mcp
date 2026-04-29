# mcp-tool-handlers Spec Delta

## MODIFIED Requirements

### Requirement: Tool Description Style
7 个 tool 的 `description` 字段 SHALL 遵循"when-to-use 在前、做什么在后"的中文单句格式，单句长度 SHALL 不超过 50 字，且 SHALL 不引入 examples 字段。每个 tool 的 description 语义要点 SHALL 与下表一致：

| Tool | description 语义要点 |
|---|---|
| `list_sources` | 首次进入项目时调用：发现可查询的日志源、确认文件状态 |
| `query` | 已知过滤条件时使用：按级别 / 字段 / 时间窗口精确检索，支持分页 |
| `tail` | 快速看最新动态：诊断刚发生的问题，比 query 省参数 |
| `summary` | 判断服务健康状况：错误率、分位数、趋势；代码变更后第一次检查首选 |
| `cross_query` | 重建跨源调用时间线：用 correlation_id 等共享字段串起多服务事件 |
| `register_source` | 临时排障引入新源：可选 persist 持久化 |
| `unregister_source` | 清理不再需要的源：可选 persist 同步删除 |

#### Scenario: 7 个 tool description 全部更新

- **WHEN** 调用 `await list_tools()` 取出全部 Tool 实例的 `description` 字段
- **THEN** 7 个 description 内容 MUST 与上表语义要点一致，且 MUST 是"when-to-use 在前、做什么在后"的中文单句

#### Scenario: 单句长度 ≤50 字

- **WHEN** 对 `list_tools()` 返回的每个 Tool 计算 `len(description)`
- **THEN** 每条 description 长度 MUST ≤ 50

#### Scenario: 健康检查类提示词优先选 summary

- **WHEN** 空白 Agent 接到提示词"最近 5 分钟有没有报错"并基于 description 选型
- **THEN** Agent MUST 优先选择 `summary` 而非 `query`，因为 `summary.description` 明确指向"判断服务健康状况"

#### Scenario: 链路回放类提示词优先选 cross_query

- **WHEN** 空白 Agent 接到提示词"按 trace_id=abc 回放调用"并基于 description 选型
- **THEN** Agent MUST 优先选择 `cross_query`，因为其 description 明确指向"重建跨源调用时间线"

#### Scenario: description 不含 examples 字段

- **WHEN** 检视每个 Tool 实例的字段集合
- **THEN** MUST 仅依赖 `description` 文本表达 when-to-use 语义，MUST 不引入 `examples` 字段
