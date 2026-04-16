"""
DuckDB SQL 查询引擎。
替代 reader.py + query.py 的内存处理方式，直接用 SQL 完成过滤、聚合。
"""

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import duckdb

# 模块级连接复用，避免每次查询重建连接
_conn: duckdb.DuckDBPyConnection | None = None


def _get_conn() -> duckdb.DuckDBPyConnection:
    """获取或创建模块级 DuckDB 内存连接。"""
    global _conn
    if _conn is None:
        _conn = duckdb.connect(":memory:")
    return _conn


# ---------------------------------------------------------------------------
# 文件发现（从 reader.py 迁移，逻辑完全一致）
# ---------------------------------------------------------------------------

def discover_files(path: str, rotation: str) -> list[Path]:
    """
    发现主日志文件及其轮转历史文件，按从新到旧排序返回。
    - numeric: file, file.1, file.2 ...
    - date:    base.YYYY-MM-DD.ext（日期越新越靠前）
    - none:    仅主文件
    """
    main = Path(path)
    parent = main.parent
    stem = main.name

    if rotation == "none":
        return [main] if main.exists() else []

    if rotation == "numeric":
        files = [main] if main.exists() else []
        i = 1
        while True:
            rotated = parent / f"{stem}.{i}"
            if not rotated.exists():
                break
            files.append(rotated)
            i += 1
        return files

    if rotation == "date":
        suffix = main.suffix
        base = main.stem
        date_pattern = re.compile(
            r"^" + re.escape(base) + r"\.\d{4}-\d{2}-\d{2}" + re.escape(suffix) + r"$"
        )
        rotated_files = [
            f for f in parent.iterdir()
            if date_pattern.match(f.name)
        ]
        rotated_files.sort(key=lambda f: f.name, reverse=True)
        result = []
        if main.exists():
            result.append(main)
        result.extend(rotated_files)
        return result

    raise ValueError(f"不支持的 rotation 类型: {rotation!r}")


# ---------------------------------------------------------------------------
# 时间解析
# ---------------------------------------------------------------------------

def _parse_time(expr: str) -> str:
    """
    解析时间表达式，返回 ISO 8601 字符串（含时区）。
    - ISO 8601：补全时区后直接返回
    - 相对值：30s / 5m / 1h / 1d 转为绝对时间字符串
    """
    expr = expr.strip()

    # 先尝试 ISO 8601 解析
    try:
        dt = datetime.fromisoformat(expr.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        pass

    # 相对时间解析
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    m = re.fullmatch(r"(\d+)([smhd])", expr)
    if m:
        seconds = int(m.group(1)) * units[m.group(2)]
        dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return dt.isoformat()

    raise ValueError(f"无法解析时间表达式: {expr!r}")


# ---------------------------------------------------------------------------
# SQL 构建层
# ---------------------------------------------------------------------------

def _read_source_sql(files: list[Path], fmt: str) -> str:
    """
    生成读取日志文件的 FROM 子查询 SQL 片段。
    - jsonl: read_json_auto，自动推断字段类型
    - text:  read_csv，所有内容作为 message 列
    """
    # DuckDB 文件列表需要用字符串数组表示
    file_list = ", ".join(f"'{f}'" for f in files)

    if fmt == "jsonl":
        return (
            f"read_json_auto([{file_list}], ignore_errors=true, filename=true)"
        )
    else:
        # text 格式：单列 CSV，列名设为 message
        return (
            f"read_csv([{file_list}], header=false, "
            f"columns={{'column0': 'VARCHAR'}})"
        )


def _normalize_select(fmt: str, field_map: dict, source_name: str) -> str:
    """
    生成字段归一化的 SELECT 表达式。
    将 field_map 中配置的原始字段名映射为 _timestamp/_level/_message 标准字段。
    """
    ts_field = field_map.get("timestamp", "timestamp")
    level_field = field_map.get("level", "level")
    msg_field = field_map.get("message", "message")

    if fmt == "jsonl":
        return (
            f"*, "
            f'"{ts_field}" AS _timestamp, '
            f'"{level_field}" AS _level, '
            f'"{msg_field}" AS _message, '
            f"'{source_name}' AS _source"
        )
    else:
        # text 格式只有 message 列
        return (
            f"column0 AS message, "
            f"NULL AS _timestamp, "
            f"NULL AS _level, "
            f"column0 AS _message, "
            f"'{source_name}' AS _source"
        )


def _parse_filter_expr(field: str, expr: str, params: list) -> str:
    """
    将单个字段过滤表达式转为参数化 SQL 片段。
    迁移自 query.py 的 match_filter 逻辑，转为 SQL 表达。
    field 参数是字段名，expr 是过滤表达式。
    """
    # 参数位置索引从 1 开始
    def _next_param(value) -> str:
        params.append(value)
        return f"${len(params)}"

    col = f'CAST("{field}" AS VARCHAR)'

    if expr.startswith("~"):
        # 正则匹配
        p = _next_param(expr[1:])
        return f"regexp_matches({col}, {p})"

    if expr.startswith(">="):
        p = _next_param(float(expr[2:]))
        return f"CAST({col} AS DOUBLE) >= {p}"

    if expr.startswith("<="):
        p = _next_param(float(expr[2:]))
        return f"CAST({col} AS DOUBLE) <= {p}"

    if expr.startswith(">"):
        p = _next_param(float(expr[1:]))
        return f"CAST({col} AS DOUBLE) > {p}"

    if expr.startswith("<"):
        p = _next_param(float(expr[1:]))
        return f"CAST({col} AS DOUBLE) < {p}"

    if expr.startswith("!"):
        p = _next_param(expr[1:])
        return f'("{field}" != {p} OR "{field}" IS NULL)'

    # 默认精确匹配
    p = _next_param(expr)
    return f"{col} = {p}"


def _build_where(
    level: str | None,
    message_pattern: str | None,
    field_filters: dict | None,
    since: str | None,
    until: str | None,
) -> tuple[str, list]:
    """
    构建 WHERE 子句及对应的参数列表。
    所有用户输入通过 $N 参数传入，禁止字符串拼接。
    返回 (where_clause, params)，where_clause 不含 "WHERE" 关键字。
    """
    clauses: list[str] = []
    params: list = []

    if level:
        params.append(level.lower())
        clauses.append(f"LOWER(_level) = ${len(params)}")

    if message_pattern:
        params.append(message_pattern)
        clauses.append(f"regexp_matches(CAST(_message AS VARCHAR), ${len(params)})")

    if since:
        params.append(_parse_time(since))
        clauses.append(f"CAST(_timestamp AS TIMESTAMPTZ) >= ${len(params)}")

    if until:
        params.append(_parse_time(until))
        clauses.append(f"CAST(_timestamp AS TIMESTAMPTZ) <= ${len(params)}")

    if field_filters:
        for field, expr in field_filters.items():
            clause = _parse_filter_expr(field, str(expr), params)
            clauses.append(clause)

    if not clauses:
        return "", params

    return " AND ".join(clauses), params


# ---------------------------------------------------------------------------
# 执行层
# ---------------------------------------------------------------------------

def _execute(sql: str, params: list) -> list[dict]:
    """执行参数化 SQL，将结果转为 dict 列表。"""
    conn = _get_conn()
    if params:
        result = conn.execute(sql, params)
    else:
        result = conn.execute(sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def _build_base_sql(source_cfg: dict, source_name: str) -> tuple[str, str]:
    """
    构建基础 FROM 子句和 SELECT 归一化表达式。
    返回 (select_expr, from_clause)。
    """
    path = source_cfg["path"]
    rotation = source_cfg["rotation"]
    fmt = source_cfg["format"]
    field_map = source_cfg.get("field_map") or {}

    files = discover_files(path, rotation)
    if not files:
        return "", ""

    from_clause = _read_source_sql(files, fmt)
    select_expr = _normalize_select(fmt, field_map, source_name)
    return select_expr, from_clause


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def query_entries(
    source_name: str,
    source_cfg: dict,
    level: str | None = None,
    message_pattern: str | None = None,
    field_filters: dict | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    按条件查询日志条目，结果按 _timestamp ASC 排序。
    返回 {"total_matched": int, "entries": list[dict]}。
    """
    select_expr, from_clause = _build_base_sql(source_cfg, source_name)
    if not from_clause:
        return {"total_matched": 0, "entries": []}

    where_str, params = _build_where(level, message_pattern, field_filters, since, until)
    where_clause = f"WHERE {where_str}" if where_str else ""

    # 子查询先归一化，外层再过滤和排序
    base_sql = f"SELECT {select_expr} FROM {from_clause}"
    count_sql = f"SELECT COUNT(*) AS cnt FROM ({base_sql}) t {where_clause}"
    total_rows = _execute(count_sql, params)
    total = total_rows[0]["cnt"] if total_rows else 0

    data_sql = (
        f"SELECT * FROM ({base_sql}) t "
        f"{where_clause} "
        f"ORDER BY _timestamp ASC NULLS LAST "
        f"LIMIT {int(limit)} OFFSET {int(offset)}"
    )
    entries = _execute(data_sql, list(params))

    return {"total_matched": total, "entries": entries}


def tail_entries(
    source_name: str,
    source_cfg: dict,
    count: int = 20,
    level: str | None = None,
    field_filters: dict | None = None,
) -> dict:
    """
    获取最新 N 条日志，结果按 _timestamp DESC 排序。
    返回 {"total_matched": int, "entries": list[dict]}。
    """
    select_expr, from_clause = _build_base_sql(source_cfg, source_name)
    if not from_clause:
        return {"total_matched": 0, "entries": []}

    where_str, params = _build_where(level, None, field_filters, None, None)
    where_clause = f"WHERE {where_str}" if where_str else ""

    base_sql = f"SELECT {select_expr} FROM {from_clause}"
    count_sql = f"SELECT COUNT(*) AS cnt FROM ({base_sql}) t {where_clause}"
    total_rows = _execute(count_sql, params)
    total = total_rows[0]["cnt"] if total_rows else 0

    data_sql = (
        f"SELECT * FROM ({base_sql}) t "
        f"{where_clause} "
        f"ORDER BY _timestamp DESC NULLS LAST "
        f"LIMIT {int(count)}"
    )
    entries = _execute(data_sql, list(params))

    return {"total_matched": total, "entries": entries}


_BUCKET_INTERVALS = {
    "1m": "INTERVAL '1 minute'",
    "5m": "INTERVAL '5 minutes'",
    "1h": "INTERVAL '1 hour'",
}


def summarize_entries(
    source_name: str,
    source_cfg: dict,
    since: str | None = "5m",
    field_filters: dict | None = None,
    group_by: str | None = None,
    percentile_fields: list[str] | None = None,
    bucket_interval: str | None = None,
) -> dict:
    """
    对日志条目进行聚合统计。
    返回 {"time_range": [...], "total": int, "level_counts": {}, "top_messages": [...]}。
    可选：percentiles, time_buckets, groups。
    """
    select_expr, from_clause = _build_base_sql(source_cfg, source_name)
    if not from_clause:
        return {
            "time_range": [],
            "total": 0,
            "level_counts": {},
            "top_messages": [],
        }

    where_str, params = _build_where(None, None, field_filters, since, None)
    where_clause = f"WHERE {where_str}" if where_str else ""

    base_sql = f"SELECT {select_expr} FROM {from_clause}"
    filtered_sql = f"SELECT * FROM ({base_sql}) t {where_clause}"

    # 1. 基础统计
    stats_rows = _execute(
        f"SELECT COUNT(*) AS total, "
        f"MIN(_timestamp) AS earliest, MAX(_timestamp) AS latest "
        f"FROM ({filtered_sql}) s",
        list(params),
    )
    stats = stats_rows[0] if stats_rows else {}
    total = stats.get("total", 0) or 0
    earliest = stats.get("earliest")
    latest = stats.get("latest")
    time_range = []
    if earliest is not None and latest is not None:
        time_range = [str(earliest), str(latest)]

    # 2. level 分布
    level_rows = _execute(
        f"SELECT LOWER(CAST(_level AS VARCHAR)) AS lvl, COUNT(*) AS cnt "
        f"FROM ({filtered_sql}) s "
        f"WHERE _level IS NOT NULL "
        f"GROUP BY 1",
        list(params),
    )
    level_counts = {row["lvl"]: row["cnt"] for row in level_rows if row["lvl"]}

    # 3. top 消息
    msg_rows = _execute(
        f"SELECT CAST(_message AS VARCHAR) AS msg, COUNT(*) AS cnt "
        f"FROM ({filtered_sql}) s "
        f"WHERE _message IS NOT NULL "
        f"GROUP BY 1 ORDER BY cnt DESC LIMIT 10",
        list(params),
    )
    top_messages = [{"message": row["msg"], "count": row["cnt"]} for row in msg_rows]

    result: dict = {
        "time_range": time_range,
        "total": total,
        "level_counts": level_counts,
        "top_messages": top_messages,
    }

    # 4. 按指定字段分组（可选）
    if group_by:
        group_rows = _execute(
            f'SELECT CAST("{group_by}" AS VARCHAR) AS grp, '
            f"COUNT(*) AS total, "
            f"SUM(CASE WHEN LOWER(CAST(_level AS VARCHAR))='error' THEN 1 ELSE 0 END) AS errors "
            f"FROM ({filtered_sql}) s "
            f"GROUP BY 1",
            list(params),
        )
        result["groups"] = {
            row["grp"]: {"total": row["total"], "errors": row["errors"]}
            for row in group_rows
        }

    # 5. 分位数统计（可选）
    if percentile_fields:
        percentiles: dict = {}
        for field in percentile_fields:
            pct_rows = _execute(
                f'SELECT '
                f'approx_quantile(CAST("{field}" AS DOUBLE), 0.5) AS p50, '
                f'approx_quantile(CAST("{field}" AS DOUBLE), 0.95) AS p95, '
                f'approx_quantile(CAST("{field}" AS DOUBLE), 0.99) AS p99 '
                f"FROM ({filtered_sql}) s "
                f'WHERE "{field}" IS NOT NULL',
                list(params),
            )
            if pct_rows:
                row = pct_rows[0]
                percentiles[field] = {"p50": row["p50"], "p95": row["p95"], "p99": row["p99"]}
        result["percentiles"] = percentiles

    # 6. 时间桶分析（可选）
    if bucket_interval and bucket_interval in _BUCKET_INTERVALS:
        interval = _BUCKET_INTERVALS[bucket_interval]
        bucket_rows = _execute(
            f"SELECT time_bucket({interval}, CAST(_timestamp AS TIMESTAMPTZ)) AS bucket, "
            f"COUNT(*) AS total, "
            f"SUM(CASE WHEN LOWER(CAST(_level AS VARCHAR))='error' THEN 1 ELSE 0 END) AS errors "
            f"FROM ({filtered_sql}) s "
            f"WHERE _timestamp IS NOT NULL "
            f"GROUP BY 1 ORDER BY 1 ASC",
            list(params),
        )
        result["time_buckets"] = [
            {"bucket": str(row["bucket"]), "total": row["total"], "errors": row["errors"]}
            for row in bucket_rows
        ]

    return result


# ---------------------------------------------------------------------------
# 跨源关联查询
# ---------------------------------------------------------------------------

# join_field 白名单：仅允许常见安全字段名用于 JOIN
_ALLOWED_JOIN_FIELDS = {
    "correlation_id", "request_id", "trace_id", "session_id",
    "user_id", "transaction_id", "span_id", "order_id",
}


def cross_query(
    sources_cfg: dict[str, dict],
    join_field: str,
    level: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """
    跨源关联查询：为每个 source 构造 CTE，通过 INNER JOIN ON join_field 关联。
    返回 {"entries": list[dict]}，每条记录按 _timestamp 排序。
    """
    if join_field not in _ALLOWED_JOIN_FIELDS:
        return {"error": f"join_field '{join_field}' 不在白名单中，允许: {', '.join(sorted(_ALLOWED_JOIN_FIELDS))}"}

    source_names = list(sources_cfg.keys())
    if len(source_names) < 2:
        return {"error": "cross_query 至少需要 2 个源"}

    cte_parts: list[str] = []
    all_params: list = []

    for i, (name, cfg) in enumerate(sources_cfg.items()):
        select_expr, from_clause = _build_base_sql(cfg, name)
        if not from_clause:
            return {"error": f"源 '{name}' 无可用文件"}

        where_str, params = _build_where(level, None, None, since, None)
        # 重新编号参数，使各 CTE 的参数不冲突
        offset = len(all_params)
        adjusted_where = where_str
        for j in range(len(params), 0, -1):
            adjusted_where = adjusted_where.replace(f"${j}", f"${j + offset}")
        all_params.extend(params)

        where_clause = f"WHERE {adjusted_where}" if adjusted_where else ""
        alias = f"s{i}"
        cte_parts.append(
            f"{alias} AS (SELECT * FROM (SELECT {select_expr} FROM {from_clause}) t {where_clause})"
        )

    # 构建 INNER JOIN：s0 JOIN s1 ON join_field，结果取 s0 全部列
    first = "s0"
    join_clauses = []
    for i in range(1, len(source_names)):
        alias = f"s{i}"
        join_clauses.append(
            f'INNER JOIN {alias} ON {first}."{join_field}" = {alias}."{join_field}"'
        )

    joins_str = " ".join(join_clauses)
    ctes_str = ", ".join(cte_parts)

    sql = (
        f"WITH {ctes_str} "
        f"SELECT {first}.* FROM {first} {joins_str} "
        f"ORDER BY {first}._timestamp ASC NULLS LAST "
        f"LIMIT {int(limit)}"
    )

    entries = _execute(sql, all_params)
    return {"entries": entries}
