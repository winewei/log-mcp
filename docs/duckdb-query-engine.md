# DuckDB 查询引擎重构方案

## 1. 动机

当前 `reader.py`（137 行）+ `query.py`（224 行）实现了一套自研查询引擎：逐行 `json.loads` 解析、Python 循环过滤、手写聚合。存在以下瓶颈：

| 问题 | 影响 |
|------|------|
| `query` 全量加载文件到内存再过滤 | 大日志文件 OOM 风险 |
| 无跨源关联 | 跨服务/跨端调用链排障需手动分别查询，无法自动关联 |
| 无分页 | 大结果集只能截断，无法定位中间段 |
| `tail` 启发式读取 `count * 2` 行 | 过滤命中率低时返回不足 |
| 聚合仅支持 count + top-10 | 无分位数、时间桶、趋势分析 |
| 自研过滤器约 200 行 | 维护成本高，边界情况多 |

DuckDB 作为嵌入式分析数据库，原生支持 JSONL 文件直读、SQL 过滤/聚合/JOIN，可一次性解决上述全部问题。

## 2. 架构变更

### 2.1 变更前

```
server.py → reader.py (文件发现/读取/解析) → query.py (归一化/过滤/聚合)
                 │                                    │
            discover_files()                   normalize()
            read_forward()                     match_filter()
            read_reverse()                     filter_entries()
            parse_line()                       summarize()
```

### 2.2 变更后

```
server.py → engine.py (SQL 生成 + DuckDB 执行)
                │
          build_query()      ← 将 MCP 参数转为参数化 SQL
          execute()          ← DuckDB 执行，返回结构化结果
          discover_files()   ← 保留轮转文件发现逻辑（供 glob 构造）
```

**删除**：`reader.py`、`query.py`
**新增**：`engine.py`（约 200 行）
**修改**：`server.py`（handler 调用从 reader+query 切换到 engine）
**不变**：`config.py`、`__main__.py`、`sources.yaml` 格式

### 2.3 依赖变更

```toml
# 新增
dependencies = [
    "mcp>=1.0",
    "pyyaml>=6.0",
    "duckdb>=1.2",       # +新增
]
```

## 3. 核心设计：engine.py

### 3.1 DuckDB 读取 JSONL

```python
import duckdb

def _read_source_sql(files: list[str], field_map: dict) -> str:
    """构造读取 + 归一化的基础 SQL"""
    file_list = ", ".join(f"'{f}'" for f in files)
    ts_field = field_map.get("timestamp", "timestamp")
    level_field = field_map.get("level", "level")
    msg_field = field_map.get("message", "message")

    return f"""
        SELECT *,
               "{ts_field}" AS _timestamp,
               "{level_field}" AS _level,
               "{msg_field}" AS _message,
               filename AS _file
        FROM read_json_auto([{file_list}],
                            format = 'newline_delimited',
                            ignore_errors = true,
                            filename = true)
    """
```

- `read_json_auto` 自动推断 schema，无需预定义列
- `ignore_errors = true` 等价于当前"跳过解析失败行"的行为
- `filename = true` 附带来源文件名，便于调试

### 3.2 过滤器到 SQL WHERE 的映射

当前 `field_filters` 语法与 SQL 的对应关系：

| MCP 过滤语法 | SQL 等价 | 示例 |
|---|---|---|
| `"value"` 精确匹配 | `= $N` | `user_id = '42'` |
| `"~pattern"` 正则 | `regexp_matches(col, $N)` | `regexp_matches(path, '/api/v1/auth.*')` |
| `">=N"` 数值比较 | `CAST(col AS DOUBLE) >= $N` | `CAST(status AS DOUBLE) >= 400` |
| `"<=N"` / `">N"` / `"<N"` | 同上 | |
| `"!value"` 取反 | `col != $N` 或 `col IS NULL` | `env != 'production'` |

**安全性**：所有用户输入通过 DuckDB 参数化查询（`$1`, `$2`, ...）传入，杜绝 SQL 注入。

```python
def _build_where(
    level: str | None,
    message_pattern: str | None,
    field_filters: dict | None,
    since: datetime | None,
    until: datetime | None,
) -> tuple[str, list]:
    """返回 (WHERE 子句, 参数列表)"""
    clauses = []
    params = []
    idx = 1

    if level:
        clauses.append(f"lower(_level) = ${idx}")
        params.append(level.lower())
        idx += 1

    if message_pattern:
        clauses.append(f"regexp_matches(CAST(_message AS VARCHAR), ${idx})")
        params.append(message_pattern)
        idx += 1

    if since:
        clauses.append(f"CAST(_timestamp AS TIMESTAMPTZ) >= ${idx}")
        params.append(since)
        idx += 1

    if until:
        clauses.append(f"CAST(_timestamp AS TIMESTAMPTZ) <= ${idx}")
        params.append(until)
        idx += 1

    if field_filters:
        for field, expr in field_filters.items():
            clause, param = _parse_filter_expr(field, expr, idx)
            clauses.append(clause)
            params.append(param)
            idx += 1

    where = " AND ".join(clauses) if clauses else "1=1"
    return f"WHERE {where}", params
```

### 3.3 六个工具的 SQL 实现

#### list_sources

不涉及 DuckDB，保持原逻辑（读 registry + `stat()` 文件状态）。

#### query

```sql
WITH source AS (
    SELECT *, "{ts}" AS _timestamp, "{level}" AS _level, "{msg}" AS _message
    FROM read_json_auto([file1, file2, ...],
                        format='newline_delimited', ignore_errors=true)
)
SELECT *
FROM source
WHERE {conditions}
ORDER BY _timestamp ASC
LIMIT $limit OFFSET $offset
```

- 新增 `offset` 参数（默认 0），实现游标分页
- `LIMIT` + `OFFSET` 由 DuckDB 执行，不加载全量数据到 Python

#### tail

```sql
WITH source AS (...)
SELECT *
FROM source
WHERE {conditions}
ORDER BY _timestamp DESC
LIMIT $count
```

DuckDB 全扫描后排序取 top-N。对典型日志文件（<100MB）耗时可忽略，且结果精确——不再有"启发式读 count*2 行可能不够"的问题。

#### summary

```sql
-- 基础统计
SELECT
    min(_timestamp) AS earliest,
    max(_timestamp) AS latest,
    count(*) AS total,
    count(*) FILTER (WHERE lower(_level) = 'error') AS errors,
    count(*) FILTER (WHERE lower(_level) = 'warning') AS warnings,
    count(*) FILTER (WHERE lower(_level) = 'info') AS info_count,
    count(*) FILTER (WHERE lower(_level) = 'debug') AS debug_count
FROM source
WHERE {time_conditions};

-- Top 消息
SELECT _message, count(*) AS cnt
FROM source WHERE {time_conditions}
GROUP BY _message ORDER BY cnt DESC LIMIT 10;

-- 分组统计（当 group_by 指定时）
SELECT {group_by},
       count(*) AS total,
       count(*) FILTER (WHERE lower(_level) = 'error') AS errors
FROM source WHERE {time_conditions}
GROUP BY {group_by}
ORDER BY total DESC;
```

#### register_source / unregister_source

不涉及 DuckDB，保持原逻辑。

## 4. 新增能力

### 4.1 跨源关联查询（新工具 `cross_query`）

DuckDB 的 JOIN 能力使跨源关联成为一等操作：

```sql
SELECT
    a._timestamp AS server_ts,
    a._level AS server_level,
    a._message AS server_event,
    a.status,
    a.duration_ms,
    b._timestamp AS client_ts,
    b._message AS client_event
FROM api_server a
JOIN client_log b ON a.correlation_id = b.correlation_id
WHERE a._level = 'error'
ORDER BY a._timestamp
```

**工具定义**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sources` | string[] | 是 | 参与关联的源名称列表 |
| `join_field` | string | 是 | 关联字段（如 `correlation_id`） |
| `level` | string | 否 | 过滤级别（应用于所有源） |
| `since` | string | 否 | 时间范围 |
| `limit` | number | 否 | 返回条数，默认 50 |

**返回**：按时间排序的合并条目，每条带 `_source` 标识来源。

### 4.2 高级聚合（summary 增强）

利用 DuckDB 的分析函数，`summary` 可扩展返回：

```json
{
  "time_range": ["...", "..."],
  "total": 142,
  "level_counts": {"error": 3, "warning": 5, "info": 134},
  "top_messages": [...],
  "groups": {...},
  "percentiles": {
    "duration_ms": {"p50": 12, "p95": 89, "p99": 234}
  },
  "time_buckets": [
    {"bucket": "2026-04-04T10:00:00Z", "total": 28, "errors": 1},
    {"bucket": "2026-04-04T10:01:00Z", "total": 35, "errors": 0}
  ]
}
```

新增参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `percentile_fields` | string[] | 需要计算分位数的数值字段 |
| `bucket_interval` | string | 时间桶间隔：`1m` / `5m` / `1h` |

### 4.3 query 分页

`query` 工具新增 `offset` 参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `offset` | number | 跳过前 N 条，默认 0 |

配合 `limit` 实现标准分页。

## 5. DuckDB 连接管理

```python
import duckdb

# 每次工具调用创建临时连接，无需持久化数据
def _execute(sql: str, params: list) -> list[dict]:
    con = duckdb.connect(":memory:")
    try:
        result = con.execute(sql, params)
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]
    finally:
        con.close()
```

- 使用 `:memory:` 模式，不创建磁盘数据库
- `read_json_auto` 直接从日志文件读取，DuckDB 只作为查询引擎
- 无状态：每次调用独立，无需管理连接池或事务

**优化**：对于 `tail` 场景（高频调用），可考虑复用连接避免重复初始化：

```python
_conn: duckdb.DuckDBPyConnection | None = None

def _get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        _conn = duckdb.connect(":memory:")
    return _conn
```

## 6. text 格式处理

DuckDB 对纯文本日志使用 `read_csv` 单列模式：

```python
if fmt == "text":
    sql = f"""
        SELECT column0 AS message, column0 AS _message
        FROM read_csv([{file_list}],
                      header=false,
                      columns={{'column0': 'VARCHAR'}})
    """
```

文本格式下仅 `message_pattern`（正则）过滤可用，与当前行为一致。

## 7. 迁移策略

### 7.1 分步执行

| 步骤 | 内容 | 影响 |
|------|------|------|
| 1 | 新增 `engine.py`，实现 DuckDB 查询层 | 无破坏性 |
| 2 | `server.py` 中 `query`/`tail`/`summary` handler 切换到 `engine.py` | 替换核心路径 |
| 3 | 验证所有现有工具行为与之前一致 | 回归验证 |
| 4 | 删除 `reader.py`、`query.py` | 清理 |
| 5 | 新增 `cross_query` 工具 | 新能力 |
| 6 | 扩展 `summary` 和 `query` 参数 | 新能力 |

### 7.2 兼容性

- `sources.yaml` 格式不变
- 6 个现有工具的参数和返回结构不变
- `field_filters` 语法完全兼容（`~`, `>=`, `!` 等）
- `register_source` / `unregister_source` 逻辑不变

### 7.3 破坏性变更

无。所有变更对 MCP 客户端（Claude Code）透明。

## 8. 变更后项目结构

```
log-mcp/
├── pyproject.toml               # +duckdb 依赖
├── sources.yaml
├── DESIGN.md                    # 更新架构描述
├── docs/
│   └── duckdb-query-engine.md   # 本文档
└── log_mcp/
    ├── __init__.py
    ├── __main__.py
    ├── server.py                # handler 调用 engine 替代 reader+query
    ├── config.py                # 不变
    └── engine.py                # 新增：SQL 生成 + DuckDB 执行
```

## 9. 性能预期

| 场景 | 当前（Python 循环） | DuckDB |
|------|-----|--------|
| 10MB JSONL 全量 query | ~2s（全量 json.loads + 过滤） | ~0.1s（向量化扫描） |
| 100MB JSONL query with time range | OOM 风险（全量加载） | ~0.3s（流式扫描 + 提前终止） |
| tail 20 条（命中率 10%） | 可能返回 <20 条 | 精确 20 条 |
| 跨 2 源 JOIN on correlation_id | 不支持 | ~0.2s |
| summary group_by + percentile | 仅 count | 完整分析 |

## 10. 风险与应对

| 风险 | 应对 |
|------|------|
| duckdb 包体积 ~50MB | MCP server 本地运行，体积不敏感 |
| `read_json_auto` schema 推断可能不稳定 | 可指定 `columns` 参数显式声明字段类型 |
| tail 场景 DuckDB 全扫描 vs 当前反向读取 | 典型文件 <100MB 时 DuckDB 扫描足够快（<0.1s） |
| SQL 注入 | 全部参数化查询，用户输入不拼接进 SQL 字符串 |
| 字段名含特殊字符 | DuckDB 双引号包裹字段名 |
