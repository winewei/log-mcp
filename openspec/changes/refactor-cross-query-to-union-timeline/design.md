# Design: cross_query 由 INNER JOIN 重构为 UNION ALL 时间线

## 1. 决策上下文

### 1.1 现状缺陷

`log_mcp/engine.py` 中 `cross_query` 当前实现存在两个事实层面的语义错误：

```sql
WITH s0 AS (...), s1 AS (...)
SELECT s0.* FROM s0 INNER JOIN s1 ON s0.correlation_id = s1.correlation_id
ORDER BY s0._timestamp ASC LIMIT ?
```

- **行数笛卡尔积膨胀**：同一 `correlation_id` 在 s0 命中 N 条、在 s1 命中 M 条时，INNER JOIN 输出 N×M 行。链路重建场景下用户期望的是 N+M 条按时间线排列的事件。
- **字段丢失**：`SELECT s0.*` 仅保留第一个源的列，s1/s2 等其他源的 `_message` / 自定义业务字段全部被丢弃，Agent 无法看到后端事件细节。

跨源调用链回放（trace replay）的本质是"按 correlation_id 聚合多源事件并沿时间轴重排"，与关系代数的 INNER JOIN 语义无关。

### 1.2 真实使用场景

Agent 调用 `cross_query` 的典型 prompt：

> 用 trace_id=abc123 把 frontend / backend 两个源的日志按时间排好给我看

期望：每个源各 3-5 条事件全部返回，按 _timestamp 单一时间线交错呈现，每条带 _source 标识。

## 2. 备选方案对比

| 方案 | 描述 | 优点 | 缺点 |
|---|---|---|---|
| A. 维持 INNER JOIN | 保留现状 | 不变更接口 | 语义错误，行数膨胀 + 字段丢失，无法解决问题 |
| B. UNION ALL 单一模式 | INNER JOIN 全部替换为 UNION ALL BY NAME | 语义匹配真实需求；SQL 简单；DuckDB 原生支持 BY NAME 自动对齐 | 不再支持关系代数 JOIN（但目前无此真实需求） |
| C. 引入 mode 参数 | mode=join \| timeline 二选一 | 灵活兼容两种语义 | 参数膨胀；mode=join 当前无真实使用；增加测试矩阵；违反"等到出现真实需求再扩展"原则 |

**决策：选择 B（UNION ALL 单一模式）**。

理由：
- 当前没有任何调用方依赖 INNER JOIN 的笛卡尔积语义（因其本身就是错的）
- 真实场景 100% 是时间线回放
- 引入 mode 是过度设计，违反 `CLAUDE.md` 中"不要过度设计"约束
- 工具名保持 `cross_query`，外部接口不变，只是修正语义

## 3. SQL 实现要点

### 3.1 各 CTE 添加 _source 常量列

`_normalize_select` 已在归一化层注入 `'<source_name>' AS _source`，cross_query 直接复用即可。每个 CTE 内的行天然带有 _source 标识。

### 3.2 UNION ALL BY NAME 自动对齐

DuckDB 的 `UNION ALL BY NAME` 按列名自动对齐，缺失列补 NULL：

```sql
WITH s0 AS (
  SELECT * FROM (SELECT *, 'frontend' AS _source FROM read_json_auto([...])) t
  WHERE correlation_id = $1 AND CAST(_timestamp AS TIMESTAMPTZ) >= $2
),
s1 AS (
  SELECT * FROM (SELECT *, 'backend' AS _source FROM read_json_auto([...])) t
  WHERE correlation_id = $3 AND CAST(_timestamp AS TIMESTAMPTZ) >= $4
)
SELECT * FROM s0
UNION ALL BY NAME
SELECT * FROM s1
ORDER BY _timestamp ASC NULLS LAST
LIMIT $5
```

注意：当前 `_build_where` 接受 `level` / `since` 但不接受 `correlation_id` 等业务字段；`cross_query` 的 join_field 等值过滤需作为 `field_filters={join_field: <value>}` 由调用方传入，或在 cross_query 内部追加该过滤。本次重构保持现有"join_field 仅作过滤维度由调用方在 field_filters 提供 / 由 since/level 共同筛选"的接口形态，重点改 SQL 结构。

### 3.3 since 默认值

旧实现：`since=None` → 全表扫描。
新实现：`since=None` → 内部默认 `"1h"`，显式调用 `_parse_time("1h")`。

理由：跨源时间线场景天然有时间窗口语义，无界扫描会拖慢响应并放大上下文。1h 是 trace 排障的常见窗口。调用方需要更长可显式传 `since="1d"` 等。

### 3.4 排序与 LIMIT

```sql
ORDER BY _timestamp ASC NULLS LAST
LIMIT <limit>
```

NULLS LAST 保证 text 格式下时间戳缺失的行不会污染前部。

## 4. 兼容性影响

| 维度 | 是否变更 | 说明 |
|---|---|---|
| 工具名 | 不变 | 仍是 `cross_query` |
| 必填参数 | 不变 | sources / join_field |
| 可选参数 | 增加 fields | 来自公共字段裁剪层（依赖 add-field-projection-layer）|
| since 默认值 | 变更 | None → "1h" |
| 返回行数 | 变更 | N×M → N+M |
| 返回字段 | 变更 | 仅 s0.* → 全部源字段（缺失 NULL） |
| _source 字段 | 始终存在 | 由 _normalize_select 注入 |
| 错误格式 | 变更 | 裸 `{"error": "..."}` → 结构化 `error_code=join_field_not_allowed` |

外部 MCP 调用方接口签名不破坏（仅新增可选 fields），但返回结构在行数和字段上有语义变化，属于行为修正而非破坏性变更——因为旧返回结构本就是错误的。

## 5. 与 add-field-projection-layer 的协作点

- `cross_query` 输出在 `_execute()` 之后、序列化之前调用公共 `_project_fields(entries, fields)` 函数
- 默认 4KB 单字段截断对 cross_query 同样适用（多源合并后大字段更易爆 context）
- 永远保留字段集合包含 `_source`（在 timeline 场景下源标识不可裁剪）
- 当调用方传 `fields=["_timestamp", "_source", "_message", "correlation_id"]` 时，cross_query 输出 entry 仅含这四列，跨源混合的大业务字段完全省略

## 6. 与 add-structured-error-response 的协作点

- `join_field` 不在白名单 → `error_code=join_field_not_allowed` + `hints={"allowed": [...白名单全集...]}`
- 源数 < 2 → 现有 `{"error": ...}` 由错误层统一改写（不在本 change 范围细化，由 add-structured-error-response 覆盖）
- 任意源无可用文件 → 由 add-structured-error-response 决定 error_code（建议 `source_not_found` 或新增 `source_no_files`）

## 7. 不引入的复杂度

- 不引入 mode 参数
- 不引入 left_join / outer_join 选项
- 不修改 join_field 白名单内容
- 不修改 sources_cfg 输入结构
- 不修改 `_build_base_sql` / `_normalize_select` 现有归一化逻辑
