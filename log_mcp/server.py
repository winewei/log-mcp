"""
MCP Server 定义：注册 6 个 tools，路由到各处理函数。
"""

import json
import logging
from datetime import timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import SourceRegistry
from .engine import cross_query, query_entries, tail_entries, summarize_entries

logger = logging.getLogger(__name__)

# 全局注册表（由 __main__.py 初始化后注入）
registry: SourceRegistry = SourceRegistry()

server = Server("log-mcp")


# ---------------------------------------------------------------------------
# Tool Schema 定义
# ---------------------------------------------------------------------------

_TOOLS = [
    Tool(
        name="list_sources",
        description="列出所有已注册的日志源及其状态（文件是否存在、大小、最近修改时间）",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="query",
        description="按条件过滤日志条目，支持级别、正则、任意字段、时间范围过滤",
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
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="tail",
        description="从文件末尾反向读取最新日志，最快速的实时查看方式",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "日志源名称"},
                "count": {"type": "integer", "description": "返回条数，默认 20，最大 200"},
                "level": {"type": "string", "description": "日志级别过滤"},
                "agent_source": {"type": "string", "description": "快捷过滤 field_filters.agent_source"},
            },
            "required": ["source"],
        },
    ),
    Tool(
        name="summary",
        description="聚合统计指定时间窗口内的日志，快速判断服务健康状况",
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
        description="动态注册新的日志源，可选择是否持久化写入 sources.yaml",
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
        description="注销已注册的日志源，可选择是否从 sources.yaml 中删除",
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
        description="跨源关联查询，通过指定字段（如 correlation_id）对多个日志源执行 JOIN",
        inputSchema={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": "参与关联的日志源名称列表，至少 2 个",
                },
                "join_field": {"type": "string", "description": "用于 JOIN 关联的字段名"},
                "level": {"type": "string", "description": "日志级别过滤，应用于所有源"},
                "since": {"type": "string", "description": "时间范围起点"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 50"},
            },
            "required": ["sources", "join_field"],
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
        return [TextContent(type="text", text=json.dumps(
            {"error": "sources 至少需要 2 个日志源"}, ensure_ascii=False))]

    sources_cfg = {}
    for name in source_names:
        sources_cfg[name] = registry.get(name)

    result = cross_query(
        sources_cfg=sources_cfg,
        join_field=args["join_field"],
        level=args.get("level"),
        since=args.get("since"),
        limit=min(int(args.get("limit") or 50), 500),
    )
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2, default=str))]


# ---------------------------------------------------------------------------
# MCP 回调注册
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """将 tool 调用路由到对应处理函数，统一捕获异常。"""
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
        error = {"error": str(e)}
        return [TextContent(type="text", text=json.dumps(error, ensure_ascii=False))]
    except Exception as e:
        logger.exception("tool '%s' 执行失败", name)
        error = {"error": type(e).__name__, "detail": str(e)}
        return [TextContent(type="text", text=json.dumps(error, ensure_ascii=False))]


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
