"""
MCP Server 定义：注册 6 个 tools，路由到各处理函数。
"""

import difflib
import json
import logging
import re
from datetime import timezone
from pathlib import Path

import duckdb
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import SourceRegistry
from .engine import (
    JoinFieldNotAllowed,
    _ALLOWED_JOIN_FIELDS,
    _get_conn,
    _read_source_sql,
    cross_query,
    discover_files,
    query_entries,
    tail_entries,
    summarize_entries,
)

logger = logging.getLogger(__name__)

# 全局注册表（由 __main__.py 初始化后注入）
registry: SourceRegistry = SourceRegistry()

server = Server("log-mcp")


# ---------------------------------------------------------------------------
# 错误响应常量与构造函数
# ---------------------------------------------------------------------------

# error_code 枚举常量
ERROR_SOURCE_NOT_FOUND = "source_not_found"
ERROR_FIELD_NOT_FOUND = "field_not_found"
ERROR_TIME_PARSE_ERROR = "time_parse_error"
ERROR_JOIN_FIELD_NOT_ALLOWED = "join_field_not_allowed"
ERROR_INTERNAL = "internal_error"

# time_parse_error 的合法示例
_TIME_EXAMPLES = ["30s", "5m", "1h", "1d", "2026-04-29T12:00:00Z"]


def _make_error(
    code: str,
    detail: str,
    suggestion: str,
    hints: dict | None = None,
) -> dict:
    """
    构造结构化错误响应字典。
    :param code:       error_code 枚举值之一
    :param detail:     人类可读的中文错误说明
    :param suggestion: 单句可执行的修复动作
    :param hints:      结构化字典，便于 Agent 程序化解析
    """
    return {
        "error_code": code,
        "detail": detail,
        "suggestion": suggestion,
        "hints": hints or {},
    }


def _error_response(code: str, detail: str, suggestion: str, hints: dict | None = None) -> list[TextContent]:
    """将 _make_error 结果包装为 TextContent 列表。"""
    payload = _make_error(code, detail, suggestion, hints)
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _get_close_field_matches(field_name: str, available_fields: list[str]) -> list[str]:
    """使用 difflib 在已知字段名中找最近似的候选，最多返回 3 个。"""
    return difflib.get_close_matches(field_name, available_fields, n=3, cutoff=0.3)


# ---------------------------------------------------------------------------
# Tool Schema 定义
# ---------------------------------------------------------------------------

_TOOLS = [
    Tool(
        name="list_sources",
        description="首次进入项目时调用：发现可查询的日志源、确认文件状态",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="query",
        description="已知过滤条件时使用：按级别 / 字段 / 时间窗口精确检索，支持分页",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "日志源名称"},
                "level": {"type": "string", "description": "日志级别过滤（error/warning/info/debug）"},
                "message_pattern": {"type": "string", "description": "对 _message 字段进行正则匹配"},
                "field_filters": {
                    "type": "object",
                    "description": "任意字段过滤，值支持 ~ 正则、>=/<= 数值比较、! 取反、精确匹配",
                },
                "since": {"type": "string", "description": "起始时间，ISO 8601 或相对值如 30s/5m/1h/1d"},
                "until": {"type": "string", "description": "结束时间，格式同 since"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 50，最大 500"},
                "offset": {"type": "integer", "description": "跳过前 N 条结果，默认 0", "default": 0, "minimum": 0},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "返回字段白名单；未传时按默认裁剪"},
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="tail",
        description="快速看最新动态：诊断刚发生的问题，比 query 省参数",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "日志源名称"},
                "count": {"type": "integer", "description": "返回条数，默认 20，最大 200"},
                "level": {"type": "string", "description": "日志级别过滤"},
                "agent_source": {"type": "string", "description": "快捷过滤 field_filters.agent_source"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "返回字段白名单；未传时按默认裁剪"},
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="summary",
        description="判断服务健康状况：错误率、分位数、趋势；代码变更后第一次检查首选",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "日志源名称"},
                "since": {"type": "string", "description": "时间窗口起点，默认 5m"},
                "agent_source": {"type": "string", "description": "按 agent 来源过滤"},
                "correlation_id": {"type": "string", "description": "按测试 run ID 过滤"},
                "group_by": {"type": "string", "description": "聚合维度：path/level/agent_source 等字段名"},
                "percentile_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要计算分位数（p50/p95/p99）的数值字段列表",
                },
                "bucket_interval": {
                    "type": "string",
                    "enum": ["1m", "5m", "1h"],
                    "description": "时间桶分析粒度",
                },
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="register_source",
        description="临时排障引入新源：可选 persist 持久化",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "源名称，全局唯一"},
                "description": {"type": "string", "description": "人类可读描述"},
                "path": {"type": "string", "description": "日志文件绝对路径"},
                "format": {"type": "string", "description": "日志格式：jsonl（默认）或 text"},
                "rotation": {"type": "string", "description": "轮转方式：numeric（默认）/ date / none"},
                "field_map": {
                    "type": "object",
                    "description": "字段映射，键为 timestamp/level/message，值为源字段名",
                },
                "persist": {"type": "boolean", "description": "是否写入 sources.yaml，默认 false"},
            },
            "required": ["name", "description", "path"],
        },
    ),
    Tool(
        name="unregister_source",
        description="清理不再需要的源：可选 persist 同步删除",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "要注销的源名称"},
                "persist": {"type": "boolean", "description": "是否从 sources.yaml 中删除，默认 false"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="cross_query",
        description="重建跨源调用时间线：用 correlation_id 等共享字段串起多服务事件",
        inputSchema={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": "参与关联的日志源名称列表，至少 2 个",
                },
                "join_field": {"type": "string", "description": "用于关联的字段名，必须在白名单内（如 correlation_id、trace_id）"},
                "join_value": {"type": "string", "description": "join_field 的等值过滤值，只返回该值对应的跨源记录（如 correlation_id 的具体值）"},
                "level": {"type": "string", "description": "日志级别过滤，应用于所有源"},
                "since": {"type": "string", "description": "时间范围起点，默认 1h"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 50"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "返回字段白名单；未传时按默认裁剪"},
            },
            "required": ["sources", "join_field", "join_value"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool 处理函数
# ---------------------------------------------------------------------------

def _file_status(path: str) -> dict:
    """返回文件状态信息字典。"""
    p = Path(path)
    if not p.exists():
        return {"status": "missing", "file_size_bytes": 0, "last_modified": None}
    stat = p.stat()
    size = stat.st_size
    mtime = stat.st_mtime
    from datetime import datetime
    last_modified = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    status = "empty" if size == 0 else "ok"
    return {"status": status, "file_size_bytes": size, "last_modified": last_modified}


async def _handle_list_sources(_args: dict) -> list[TextContent]:
    sources = registry.list()
    result = []
    for name, cfg in sources.items():
        info = {"name": name, "description": cfg["description"], "path": cfg["path"], "format": cfg["format"]}
        info.update(_file_status(cfg["path"]))
        result.append(info)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _handle_query(args: dict) -> list[TextContent]:
    source_name = args["source"]
    cfg = registry.get(source_name)

    result = query_entries(
        source_name=source_name,
        source_cfg=cfg,
        level=args.get("level"),
        message_pattern=args.get("message_pattern"),
        field_filters=args.get("field_filters") or None,
        since=args.get("since"),
        until=args.get("until"),
        limit=min(int(args.get("limit") or 50), 500),
        offset=max(int(args.get("offset") or 0), 0),
        fields=args.get("fields") or None,
    )
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]


async def _handle_tail(args: dict) -> list[TextContent]:
    source_name = args["source"]
    cfg = registry.get(source_name)

    field_filters: dict = {}
    if args.get("agent_source"):
        field_filters["agent_source"] = args["agent_source"]

    result = tail_entries(
        source_name=source_name,
        source_cfg=cfg,
        count=min(int(args.get("count") or 20), 200),
        level=args.get("level"),
        field_filters=field_filters or None,
        fields=args.get("fields") or None,
    )
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]


async def _handle_summary(args: dict) -> list[TextContent]:
    source_name = args["source"]
    cfg = registry.get(source_name)

    field_filters: dict = {}
    if args.get("agent_source"):
        field_filters["agent_source"] = args["agent_source"]
    if args.get("correlation_id"):
        field_filters["correlation_id"] = args["correlation_id"]

    result = summarize_entries(
        source_name=source_name,
        source_cfg=cfg,
        since=args.get("since") or "5m",
        field_filters=field_filters or None,
        group_by=args.get("group_by"),
        percentile_fields=args.get("percentile_fields"),
        bucket_interval=args.get("bucket_interval"),
    )
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]


async def _handle_register_source(args: dict) -> list[TextContent]:
    name = args["name"]
    registry.register(
        name=name,
        description=args["description"],
        path=args["path"],
        fmt=args.get("format", "jsonl"),
        rotation=args.get("rotation", "numeric"),
        field_map=args.get("field_map"),
        persist=bool(args.get("persist", False)),
    )
    result = {"status": "registered", "name": name}
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def _handle_unregister_source(args: dict) -> list[TextContent]:
    name = args["name"]
    registry.unregister(name=name, persist=bool(args.get("persist", False)))
    result = {"status": "unregistered", "name": name}
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def _handle_cross_query(args: dict) -> list[TextContent]:
    source_names = args["sources"]
    if len(source_names) < 2:
        return _error_response(
            ERROR_INTERNAL,
            "sources 至少需要 2 个日志源",
            "请在 sources 列表中提供至少 2 个日志源名称",
            {"provided_count": len(source_names)},
        )

    sources_cfg = {}
    for name in source_names:
        sources_cfg[name] = registry.get(name)

    # 调用方未传 since 时让 engine 使用其默认值 1h，显式传 None 则透传
    kwargs: dict = {
        "sources_cfg": sources_cfg,
        "join_field": args["join_field"],
        "join_value": args["join_value"],
        "level": args.get("level"),
        "limit": min(int(args.get("limit") or 50), 500),
        "fields": args.get("fields") or None,
    }
    if "since" in args:
        kwargs["since"] = args["since"]

    result = cross_query(**kwargs)
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]


# ---------------------------------------------------------------------------
# MCP 回调注册
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """将 tool 调用路由到对应处理函数，统一捕获异常并返回结构化错误响应。"""
    handlers = {
        "list_sources": _handle_list_sources,
        "query": _handle_query,
        "tail": _handle_tail,
        "summary": _handle_summary,
        "register_source": _handle_register_source,
        "unregister_source": _handle_unregister_source,
        "cross_query": _handle_cross_query,
    }

    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"未知 tool: {name!r}")

    try:
        return await handler(arguments)
    except KeyError as e:
        # registry.get 未命中：返回 source_not_found
        available = list(registry.list().keys())
        return _error_response(
            ERROR_SOURCE_NOT_FOUND,
            f"日志源不存在: {e}",
            "请调用 list_sources 查看可用源，或调用 register_source 注册新源",
            {"available_sources": available},
        )
    except JoinFieldNotAllowed as e:
        # cross_query join_field 不在白名单：返回 join_field_not_allowed
        return _error_response(
            ERROR_JOIN_FIELD_NOT_ALLOWED,
            str(e),
            f"请使用白名单中的字段作为 join_field，可选值: {sorted(_ALLOWED_JOIN_FIELDS)}",
            {"allowed_join_fields": sorted(_ALLOWED_JOIN_FIELDS)},
        )
    except ValueError as e:
        # _parse_time 解析失败（time_parse_error），也兜住其他 ValueError
        err_msg = str(e)
        if "无法解析时间表达式" in err_msg:
            return _error_response(
                ERROR_TIME_PARSE_ERROR,
                err_msg,
                "请使用 ISO 8601 格式（如 2026-04-29T12:00:00Z）或相对值（如 30s/5m/1h/1d）",
                {"valid_examples": _TIME_EXAMPLES},
            )
        # 其他 ValueError（如 register_source 参数校验）归为 internal_error
        logger.exception("tool '%s' 执行失败（ValueError）", name)
        return _error_response(
            ERROR_INTERNAL,
            err_msg,
            "请检查参数合法性后重试",
            {"exception_type": type(e).__name__},
        )
    except duckdb.BinderException as e:
        # 字段引用失败：返回 field_not_found，并用 difflib 给出候选
        err_msg = str(e)

        # --- bad_field 推导（按优先级）---
        # 1. 优先从 field_filters 的第一个 key 取（调用方明确传了字段名）
        bad_field = ""
        filters = arguments.get("field_filters") or {}
        if isinstance(filters, dict):
            bad_field = next(iter(filters.keys()), "")

        # 通过一次原始极小查询获取文件中实际存在的列名，用于近似匹配。
        # 故意跳过 field_map 归一化（_normalize_select），避免 field_map 配置错误时 probe 本身也抛 BinderException。
        candidates: list[str] = []
        probe_error: str | None = None
        try:
            source_name = arguments.get("source", "")
            cfg = registry.get(source_name)
            field_map = cfg.get("field_map") or {}
            fmt = cfg.get("format", "jsonl")
            files = discover_files(cfg["path"], cfg.get("rotation", "none"))
            if files:
                # 用原始 read_json_auto 跳过 field_map，取文件真实列名
                raw_from = _read_source_sql(files, fmt)
                probe_sql = f"SELECT * FROM {raw_from} LIMIT 1"
                probe_result = _get_conn().execute(probe_sql)
                observed_fields = [desc[0] for desc in probe_result.description]
            else:
                observed_fields = []

            # 2. field_filters 无字段时，从 BinderException 消息正则提取缺失列名
            #    DuckDB 错误格式：Referenced column "col_name" not found in FROM clause!
            if not bad_field:
                m = re.search(r'Referenced column "([^"]+)"', err_msg)
                if m:
                    bad_field = m.group(1)

            # 3. 若正则也无法提取，退而从 field_map.values() 中找不存在于 observed_fields 的项
            #    这些是真正配置错误的 field_map 条目
            if not bad_field:
                observed_set = set(observed_fields)
                broken_map_fields = [v for v in field_map.values() if v not in observed_set]
                if broken_map_fields:
                    bad_field = broken_map_fields[0]

            # 候选池仅用 observed_fields（文件真实列名），禁止混入 field_map values。
            # field_map values 可能是错误配置的列名（根因），加入候选池会导致自匹配，误导用户。
            candidate_pool = list(observed_fields)

            if bad_field:
                candidates = difflib.get_close_matches(bad_field, candidate_pool, n=3)
                if not candidates:
                    candidates = candidate_pool[:3]

            # 4. 兜底：bad_field 仍为空时，将 observed_fields 前 3 个作为"已观察列"hints 返回
            if not candidates and observed_fields:
                candidates = observed_fields[:3]

        except Exception as probe_err:
            # probe 查询失败（文件缺失等）：候选池无法构建。
            # 不再回退到 field_map.values()——这些可能正是配置错误的列名，自匹配会误导用户。
            # 仅尝试从 BinderException 提取 bad_field 用于 detail，candidates 保持空。
            if not bad_field:
                m = re.search(r'Referenced column "([^"]+)"', err_msg)
                if m:
                    bad_field = m.group(1)
            probe_error = f"{type(probe_err).__name__}: {probe_err}"

        hints: dict = {"candidate_fields": candidates, "duckdb_error": err_msg}
        if probe_error:
            hints["probe_error"] = probe_error
        return _error_response(
            ERROR_FIELD_NOT_FOUND,
            f"字段引用失败: {err_msg}",
            "请检查 field_filters 中的字段名是否正确，或调用 list_sources 查看实际 schema",
            hints,
        )
    except Exception as e:
        # 兜底：未预期异常归为 internal_error
        logger.exception("tool '%s' 执行失败", name)
        return _error_response(
            ERROR_INTERNAL,
            f"内部错误: {type(e).__name__}: {e}",
            "请检查日志获取详细堆栈，必要时联系维护者",
            {"exception_type": type(e).__name__},
        )


# ---------------------------------------------------------------------------
# Server 启动函数（由 __main__.py 调用）
# ---------------------------------------------------------------------------

async def run_server(config_path: str | None = None) -> None:
    """初始化注册表并启动 MCP Server（stdio transport）。"""
    global registry

    if config_path:
        registry.load_from_file(config_path)
        logger.info("已加载配置文件: %s", config_path)
    else:
        logger.info("未指定配置文件，以纯动态注册模式启动")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
