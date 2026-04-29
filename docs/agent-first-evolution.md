# log-mcp Agent-first 演进方案

> **状态：已实施（2026-04-29）**
>
> 本文档是历史设计方案，对应 4 个 OpenSpec changes 已全部归档：
> - `2026-04-29-add-structured-error-response`
> - `2026-04-29-add-field-projection-layer`
> - `2026-04-29-refactor-cross-query-to-union-timeline`
> - `2026-04-29-rewrite-tool-descriptions-when-to-use`
>
> 当前实际行为以 `openspec/specs/` 与代码为准，本文档保留作为决策记录。

## 1. 背景

经过自检与代码核对，当前实现存在两个事实层面的缺陷以及一组提升 Agent 闭环效率的机会：

1. **`cross_query` 语义错误**（`log_mcp/engine.py:551`）：当前 SQL 仅 `SELECT s0.*`，多源 INNER JOIN 还会因笛卡尔积导致行数膨胀，与"按 correlation_id 回放调用链路"的真实需求不符。
2. **错误返回缺失可执行建议**（`log_mcp/server.py:304-312`）：`KeyError` / `Exception` 仅返回裸消息，Agent 撞上死字段或无效源时无法自我恢复。
3. **大字段未裁剪**：`query`/`tail`/`cross_query` 默认返回全字段 JSON，Agent 上下文易被大 body/headers 撑爆。
4. **tool description 偏功能描述、缺"when to use"**：Agent 在工具选用上需要更明确的语义引导。

本方案聚焦上述四项，目标是让 log-mcp 成为更稳定的 Agent 日志查询前端，明确不演进为通用日志平台。

## 2. 设计目标与边界

### 2.1 In-scope

| 编号 | 改动 | 性质 |
|---|---|---|
| C1 | `cross_query` 由 INNER JOIN 重构为 UNION ALL timeline | 语义修正 + 字段补齐 |
| C2 | 统一结构化错误响应（`error_code` / `detail` / `suggestion` / `hints`） | 新能力 |
| C3 | 公共字段裁剪层（默认大字段截断 + `fields` 白名单） | 新能力，跨 tool 共享 |
| C4 | tool description 重写为 "when to use" 引导 | 现有能力描述更新 |

### 2.2 Out-of-scope（明确不做）

- **不做** 查询意图模板化（Prompt-to-Tool Profiles）：用 description 的 examples 段解决，避免硬编码模板
- **不做** 会话级查询记忆：与 MCP 无状态设计冲突，Agent 自己有上下文
- **不做** 长期存储 / 冷热分层 / 告警编排 / PB 级集群检索
- **不做** 轻量质量指标埋点：当前缺乏受众与判读机制

---

## 3. C1：`cross_query` 重构为 UNION ALL Timeline

### 3.1 问题

现有实现（`log_mcp/engine.py:497-557`）：

```sql
WITH s0 AS (...), s1 AS (...)
SELECT s0.* FROM s0 INNER JOIN s1 ON s0.correlation_id = s1.correlation_id
ORDER BY s0._timestamp ASC LIMIT ?
```

两个具体缺陷：

1. **行数膨胀**：同一 `correlation_id` 在 s0 有 N 条、s1 有 M 条时，结果是 N×M 行。链路重建场景下应得到 N+M 条按时间线排列的事件。
2. **字段丢失**：`SELECT s0.*` 丢弃 s1/s2 等其他源的所有字段，Agent 看不到后端 `_message`。

### 3.2 设计

将 INNER JOIN 替换为 UNION ALL，每条记录原样保留并附 `_source` 标识，按 `_timestamp` 排序：

```sql
WITH s0 AS (
  SELECT *, 'frontend' AS _source FROM ... WHERE correlation_id = ? AND ...
),
s1 AS (
  SELECT *, 'backend'  AS _source FROM ... WHERE correlation_id = ? AND ...
)
SELECT * FROM s0
UNION ALL BY NAME
SELECT * FROM s1
ORDER BY _timestamp ASC NULLS LAST
LIMIT ?
```

### 3.3 行为变更

| 维度 | 旧 | 新 |
|---|---|---|
| 结果行数 | 各源命中数乘积 | 各源命中数之和 |
| 字段保留 | 仅 s0 字段 | 全部源字段（缺失补 NULL） |
| 排序 | 按 s0._timestamp | 按合并后的 _timestamp |
| 行级源标识 | 无 | 必须有 `_source` 字段 |
| `since` 默认值 | 无（可全表扫） | 默认 `1h`，避免无界扫描 |

### 3.4 接口约束

- 工具名保持 `cross_query`（兼容现有调用方）
- `join_field` 白名单（`_ALLOWED_JOIN_FIELDS`）继续生效，因字段名仍会拼入 SQL
- description 必须从"INNER JOIN"改写为"按 join_field 重建跨源时间线"
- 不引入 `mode` 参数：等到出现真实 JOIN 需求再扩展

### 3.5 验收 Scenario

- 单 correlation_id 在 frontend 命中 3 条、backend 命中 5 条 → 返回 8 条，按时间排序
- 每条记录包含 `_source` 字段标识来源
- 两个源字段不同时（如 frontend 有 `screen`、backend 有 `path`），UNION 结果按字段名对齐，缺失补 NULL
- `since` 缺省时按 `1h` 处理
- `join_field` 不在白名单时返回结构化错误（与 C2 联动）

---

## 4. C2：统一结构化错误响应

### 4.1 问题

`log_mcp/server.py:304-312` 当前实现：

```python
except KeyError as e:
    error = {"error": str(e)}
except Exception as e:
    error = {"error": type(e).__name__, "detail": str(e)}
```

Agent 拿到 `{"error": "BinderException", "detail": "Referenced column \"xxx\" not found"}` 后无法自动决定下一步。

### 4.2 设计

定义统一错误 schema，覆盖三类高频错误：

```json
{
  "error_code": "source_not_found",
  "detail": "日志源 'ghost' 不存在",
  "suggestion": "调用 list_sources 查看已注册源",
  "hints": {
    "available_sources": ["api-server", "worker"]
  }
}
```

### 4.3 错误分类

| error_code | 触发条件 | suggestion | hints |
|---|---|---|---|
| `source_not_found` | `registry.get()` KeyError | 调用 `list_sources` 或 `register_source` | 当前所有源名 |
| `field_not_found` | DuckDB BinderException 或 field_map 引用失败 | 检查 `field_map` 或调用 `list_sources` 查看真实 schema | 候选字段名（基于已观察到的列做近似匹配，最多 3 个） |
| `time_parse_error` | `_parse_time` ValueError | 使用 ISO 8601 或相对值 30s/5m/1h/1d | 一组合法示例 |
| `join_field_not_allowed` | `cross_query` 白名单拒绝 | 使用白名单中的字段 | 全部白名单字段 |
| `internal_error` | 其他未预期异常 | （无） | 异常类型 |

### 4.4 接口约束

- 错误响应仍是 `TextContent`，内部 JSON 结构按上表
- `suggestion` 必须是单句可执行动作，不写多段说明
- `hints` 字段是结构化数据，便于 Agent 解析；不写自然语言长篇引导
- 现有错误返回路径全部走新 schema，不保留旧字段

### 4.5 验收 Scenario

- 调用 `query(source="ghost")` → 返回 `error_code=source_not_found`，hints 含全部可用源名
- 调用 `query(source="x", field_filters={"foo": "bar"})` 而 `foo` 不存在 → 返回 `error_code=field_not_found`，hints 含候选字段名
- 调用 `query(source="x", since="yesterday")` → 返回 `error_code=time_parse_error`，hints 含示例
- 调用 `cross_query(join_field="email")` → 返回 `error_code=join_field_not_allowed`，hints 含白名单

---

## 5. C3：公共字段裁剪层

### 5.1 问题

`tail(count=20)` 在日志含大 body/headers/cookie 时一次返回可能超过 100KB，Agent 上下文受损；后续推理质量下降。

### 5.2 设计

引入跨 tool 共享的内部裁剪函数，对返回的每条 entry 执行：

1. **默认裁剪**：单字段值序列化后超过 4KB 时，替换为占位符 `"<truncated:1.2MB>"`，原值不返回
2. **白名单优先**：调用方传 `fields: ["_timestamp", "_level", "_message", "correlation_id"]` 时，仅返回白名单字段，其他字段全部省略（不参与裁剪判断）
3. **永远保留**：`_timestamp` / `_level` / `_message` / `_source` 四个归一化字段不裁剪

裁剪在 `_execute()` 之后、序列化之前统一执行。

### 5.3 接口约束

- `query` / `tail` / `cross_query` 三个 tool 增加可选参数 `fields: list[str]`
- 默认裁剪阈值 4KB 写死，不暴露为参数（避免参数膨胀）
- 裁剪发生时占位符必须包含原值大小（便于 Agent 判断是否需要二次精确查询）
- `summary` 不做裁剪（聚合结果天然小）

### 5.4 验收 Scenario

- 单字段 100KB 的 body → 默认返回 `"<truncated:100.0KB>"`
- 传 `fields=["_timestamp", "_message"]` → 返回 entry 仅含这两个字段
- 传 `fields=["nonexistent"]` → 返回 entry 中该字段为 NULL，不报错
- `_timestamp` 字段无论多大都保留原值（虽实际不会大）

---

## 6. C4：tool description 重写为 "when to use"

### 6.1 设计

7 个 tool 的 `description` 从"做什么"改写为"何时用 + 做什么"，引导 Agent 选择合适工具：

| Tool | 旧描述（节选） | 新描述方向 |
|---|---|---|
| `list_sources` | 列出所有已注册的日志源及其状态 | **首次进入项目时调用**：发现可查询的日志源、确认文件状态 |
| `query` | 按条件过滤日志条目 | **已知过滤条件时使用**：按级别 / 字段 / 时间窗口精确检索，支持分页 |
| `tail` | 从文件末尾反向读取最新日志 | **快速看最新动态**：诊断刚发生的问题，比 query 省参数 |
| `summary` | 聚合统计指定时间窗口内的日志 | **判断服务健康状况**：错误率、分位数、趋势；代码变更后第一次检查首选 |
| `cross_query` | 跨源关联查询，通过指定字段对多个日志源执行 JOIN | **重建跨源调用时间线**：用 correlation_id 等共享字段串起多服务事件 |
| `register_source` | 动态注册新的日志源 | **临时排障引入新源**：可选 persist 持久化 |
| `unregister_source` | 注销已注册的日志源 | **清理不再需要的源**：可选 persist 同步删除 |

### 6.2 约束

- 每条 description 单句，不超过 50 字
- "when to use" 在前，"做什么"在后
- 不引入 examples 字段（MCP Tool 类型不支持，且 LLM 已能从语义判断）
- 中文描述，与现有项目风格一致

### 6.3 验收 Scenario

- 7 个 tool 的 description 字段全部更新
- 在空白 Agent 上跑"最近 5 分钟有没有报错"提示词时，应优先选 `summary` 而非 `query`
- 提示词"按 trace_id=abc 回放调用"时，应选 `cross_query`

---

## 7. 实施依赖

```
C2 (错误结构) ─┐
                ├─→ C1 (cross_query 重构需引用新错误格式)
C3 (字段裁剪) ─┘

C4 (description) 与上述独立，可并行
```

C1 和 C3 都依赖 C2 的错误 schema 已定义。C4 完全独立。

## 8. 不引入的复杂度

- 不增加外部依赖
- 不修改 `config.py` 与 sources.yaml 格式
- 不引入运行时状态（Server 保持无状态）
- 不修改 `__main__.py` CLI 入口
