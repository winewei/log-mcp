"""
覆盖 log_mcp/server.py 的 MCP 协议暴露面：
  - 7 个 Tool 的 inputSchema 合法性与必填字段
  - _file_status 在 5 种文件系统状态下的返回契约
  - 7 个 _handle_* handler 的成功/错误分支
  - call_tool 统一分发与异常包装
  - run_server 启动路径（mock stdio）
"""

import asyncio
import contextlib
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from jsonschema import Draft202012Validator
from mcp.types import TextContent, Tool

import log_mcp.server as srv
from log_mcp.config import SourceRegistry, load_config


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------

def run_async(coro):
    """同步执行 async handler / coroutine。"""
    return asyncio.run(coro)


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _text(result) -> str:
    """取 handler 返回的 list[TextContent] 第一条的 text。"""
    assert isinstance(result, list) and len(result) == 1
    assert isinstance(result[0], TextContent)
    assert result[0].type == "text"
    return result[0].text


def _json(result):
    return json.loads(_text(result))


# 固定样本数据：与 conftest.jsonl_source 同款，时间戳可控
_SAMPLE_ENTRIES = [
    {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info",    "message": "http_request", "status": 200, "path": "/api/v1/login", "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 45},
    {"timestamp": "2026-04-15T10:00:02+00:00", "level": "error",   "message": "auth_failed",  "status": 500, "path": "/api/v1/auth",  "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 120},
    {"timestamp": "2026-04-15T10:00:03+00:00", "level": "info",    "message": "http_request", "status": 200, "path": "/api/v1/peers", "agent_source": "client-b", "correlation_id": "run-002", "duration_ms": 30},
    {"timestamp": "2026-04-15T10:00:04+00:00", "level": "warning", "message": "slow_query",   "status": 200, "path": "/api/v1/login", "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 800},
    {"timestamp": "2026-04-15T10:00:05+00:00", "level": "error",   "message": "db_timeout",   "status": 503, "path": "/api/v1/peers", "agent_source": "client-b", "correlation_id": "run-002", "duration_ms": 5000},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_registry(monkeypatch):
    """空 registry 注入到 server 模块全局。"""
    reg = SourceRegistry()
    monkeypatch.setattr(srv, "registry", reg)
    return reg


@pytest.fixture
def registry_with_sources(tmp_path, monkeypatch):
    """两个源：test-api（5 条日志）+ test-empty（空文件）。"""
    api_path = tmp_path / "api.jsonl"
    _write_jsonl(api_path, _SAMPLE_ENTRIES)
    empty_path = tmp_path / "empty.jsonl"
    empty_path.touch()

    reg = SourceRegistry()
    reg.register("test-api", description="API 日志", path=str(api_path))
    reg.register("test-empty", description="空文件", path=str(empty_path))
    monkeypatch.setattr(srv, "registry", reg)
    return reg


@pytest.fixture
def cross_sources_registry(tmp_path, monkeypatch):
    """两个源，共享 correlation_id 用于 cross_query。"""
    api = tmp_path / "cross_api.jsonl"
    _write_jsonl(api, [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info",  "message": "login_request", "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-15T10:00:02+00:00", "level": "error", "message": "auth_failed",   "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-15T10:00:03+00:00", "level": "info",  "message": "list_peers",    "correlation_id": "run-003", "path": "/api/peers"},
    ])
    client = tmp_path / "cross_client.jsonl"
    _write_jsonl(client, [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info", "message": "tap_login_btn", "correlation_id": "run-001", "screen": "login"},
        {"timestamp": "2026-04-15T10:00:04+00:00", "level": "info", "message": "tap_settings",  "correlation_id": "run-002", "screen": "settings"},
    ])

    reg = SourceRegistry()
    reg.register("api", description="服务端", path=str(api))
    reg.register("client", description="客户端", path=str(client))
    monkeypatch.setattr(srv, "registry", reg)
    return reg


@pytest.fixture
def persist_registry(tmp_path, monkeypatch):
    """绑定 config_path 的 registry，用于 persist 场景。"""
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text("sources: {}\n", encoding="utf-8")
    reg = SourceRegistry(config_path=str(yaml_path))
    monkeypatch.setattr(srv, "registry", reg)
    return reg, yaml_path


# ---------------------------------------------------------------------------
# §2 Tool Schema 校验
# ---------------------------------------------------------------------------

class TestToolSchema:
    def test_list_tools_returns_seven_tools(self):
        tools = run_async(srv.list_tools())
        assert len(tools) == 7
        names = {t.name for t in tools}
        assert names == {
            "list_sources", "query", "tail", "summary",
            "register_source", "unregister_source", "cross_query",
        }
        for t in tools:
            assert isinstance(t, Tool)

    def test_input_schema_is_valid_json_schema(self):
        tools = run_async(srv.list_tools())
        for t in tools:
            # check_schema 不抛即为合法
            Draft202012Validator.check_schema(t.inputSchema)

    def test_required_fields_contract(self):
        by_name = {t.name: t for t in run_async(srv.list_tools())}
        assert by_name["list_sources"].inputSchema["required"] == []
        assert by_name["query"].inputSchema["required"] == ["source"]
        assert by_name["tail"].inputSchema["required"] == ["source"]
        assert by_name["summary"].inputSchema["required"] == ["source"]
        assert by_name["register_source"].inputSchema["required"] == ["name", "description", "path"]
        assert by_name["unregister_source"].inputSchema["required"] == ["name"]
        assert by_name["cross_query"].inputSchema["required"] == ["sources", "join_field"]

    def test_cross_query_sources_has_min_items_two(self):
        by_name = {t.name: t for t in run_async(srv.list_tools())}
        sources_prop = by_name["cross_query"].inputSchema["properties"]["sources"]
        assert sources_prop["type"] == "array"
        assert sources_prop["minItems"] == 2


# ---------------------------------------------------------------------------
# §3 _file_status 多状态
# ---------------------------------------------------------------------------

class TestFileStatus:
    def test_file_exists_non_empty(self, tmp_path):
        p = tmp_path / "some.log"
        p.write_bytes(b"x")
        status = srv._file_status(str(p))
        assert status["status"] == "ok"
        assert status["file_size_bytes"] == 1
        # last_modified 必须可被 datetime.fromisoformat 解析（ISO 8601 含时区）
        from datetime import datetime
        parsed = datetime.fromisoformat(status["last_modified"])
        assert parsed.tzinfo is not None

    def test_file_exists_empty(self, tmp_path):
        p = tmp_path / "empty.log"
        p.touch()
        status = srv._file_status(str(p))
        assert status["status"] == "empty"
        assert status["file_size_bytes"] == 0
        assert status["last_modified"] is not None

    def test_file_missing(self, tmp_path):
        status = srv._file_status(str(tmp_path / "nope.log"))
        assert status["status"] == "missing"
        assert status["file_size_bytes"] == 0
        assert status["last_modified"] is None

    def test_path_is_directory(self, tmp_path):
        # 契约：不抛异常，返回 dict 含三键；status 取决于 stat().st_size（OS 行为）
        status = srv._file_status(str(tmp_path))
        assert set(status.keys()) == {"status", "file_size_bytes", "last_modified"}
        assert status["status"] in {"ok", "empty"}
        assert status["last_modified"] is not None

    def test_file_chmod_000(self, tmp_path):
        p = tmp_path / "locked.log"
        p.write_bytes(b"data")
        try:
            os.chmod(p, 0o000)
            # 文件权限为 0 时 stat() 仍可用；exists() 返回 True
            status = srv._file_status(str(p))
            assert set(status.keys()) == {"status", "file_size_bytes", "last_modified"}
            assert status["file_size_bytes"] == 4
            assert status["status"] == "ok"
        finally:
            os.chmod(p, 0o644)


# ---------------------------------------------------------------------------
# §4 Source Lifecycle Handler
# ---------------------------------------------------------------------------

class TestSourceLifecycleHandlers:
    def test_list_sources_empty_registry(self, empty_registry):
        result = run_async(srv._handle_list_sources({}))
        assert _json(result) == []

    def test_list_sources_multiple(self, registry_with_sources):
        data = _json(run_async(srv._handle_list_sources({})))
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert names == {"test-api", "test-empty"}
        required_keys = {"name", "description", "path", "format", "status", "file_size_bytes", "last_modified"}
        for item in data:
            assert required_keys <= set(item.keys())
        # test-api 非空、test-empty 为空
        status_by_name = {item["name"]: item["status"] for item in data}
        assert status_by_name["test-api"] == "ok"
        assert status_by_name["test-empty"] == "empty"

    def test_register_source_success(self, empty_registry, tmp_path):
        log = tmp_path / "new.jsonl"
        log.touch()
        result = run_async(srv._handle_register_source({
            "name": "svc-x",
            "description": "新服务",
            "path": str(log),
            "format": "jsonl",
        }))
        assert _json(result) == {"status": "registered", "name": "svc-x"}
        # registry 能检索到
        cfg = empty_registry.get("svc-x")
        assert cfg["path"] == str(log)
        assert cfg["format"] == "jsonl"

    def test_register_source_invalid_format_wrapped_by_call_tool(self, empty_registry, tmp_path):
        log = tmp_path / "x.jsonl"
        log.touch()
        result = run_async(srv.call_tool("register_source", {
            "name": "bad",
            "description": "desc",
            "path": str(log),
            "format": "invalid",
        }))
        data = _json(result)
        # 新结构化错误 schema：error_code=internal_error，detail 含错误说明
        assert data.get("error_code") == srv.ERROR_INTERNAL
        assert "format" in data.get("detail", "") or "invalid" in data.get("detail", "")
        assert "error" not in data  # 旧字段不存在
        # 注册失败 → registry 无该源
        with pytest.raises(KeyError):
            empty_registry.get("bad")

    def test_register_source_persist_writes_yaml(self, persist_registry, tmp_path):
        reg, yaml_path = persist_registry
        log = tmp_path / "persisted.jsonl"
        log.touch()
        run_async(srv._handle_register_source({
            "name": "persisted-svc",
            "description": "持久源",
            "path": str(log),
            "format": "jsonl",
            "persist": True,
        }))
        # YAML 被重写且可被 load_config 再次读出
        loaded = load_config(str(yaml_path))
        assert "persisted-svc" in loaded
        assert loaded["persisted-svc"]["path"] == str(log)

    def test_unregister_source_success(self, registry_with_sources):
        result = run_async(srv._handle_unregister_source({"name": "test-api"}))
        assert _json(result) == {"status": "unregistered", "name": "test-api"}
        with pytest.raises(KeyError):
            registry_with_sources.get("test-api")

    def test_unregister_source_missing_wrapped_by_call_tool(self, empty_registry):
        result = run_async(srv.call_tool("unregister_source", {"name": "ghost"}))
        data = _json(result)
        # 新结构化错误 schema：error_code=source_not_found
        assert data.get("error_code") == srv.ERROR_SOURCE_NOT_FOUND
        assert "ghost" in data.get("detail", "")
        assert "error" not in data  # 旧字段不存在


# ---------------------------------------------------------------------------
# §5 Query Handlers
# ---------------------------------------------------------------------------

class TestQueryHandlers:
    def test_query_success_passes_filters(self, registry_with_sources):
        result = run_async(srv._handle_query({
            "source": "test-api",
            "level": "error",
            "since": "2026-04-14T00:00:00+00:00",
            "until": "2026-04-16T00:00:00+00:00",
            "limit": 100,
        }))
        data = _json(result)
        assert "total_matched" in data
        assert "entries" in data
        assert data["total_matched"] == 2  # 2 条 error
        for entry in data["entries"]:
            assert entry["_level"] == "error"

    def test_query_missing_source_wrapped(self, empty_registry):
        result = run_async(srv.call_tool("query", {"source": "ghost"}))
        data = _json(result)
        # 新结构化错误 schema：error_code=source_not_found
        assert data.get("error_code") == srv.ERROR_SOURCE_NOT_FOUND
        assert "ghost" in data.get("detail", "")
        assert "error" not in data  # 旧字段不存在

    def test_query_limit_is_clamped_to_500(self, registry_with_sources, monkeypatch):
        captured = {}

        def spy(**kwargs):
            captured.update(kwargs)
            return {"total_matched": 0, "entries": []}

        monkeypatch.setattr(srv, "query_entries", spy)
        run_async(srv._handle_query({"source": "test-api", "limit": 1000}))
        assert captured["limit"] == 500

    def test_tail_success_with_agent_source_filter(self, registry_with_sources):
        result = run_async(srv._handle_tail({
            "source": "test-api",
            "count": 50,
            "agent_source": "client-a",
        }))
        data = _json(result)
        assert data["total_matched"] == 3  # 3 条来自 client-a
        for entry in data["entries"]:
            assert entry["agent_source"] == "client-a"

    def test_tail_missing_source_wrapped(self, empty_registry):
        result = run_async(srv.call_tool("tail", {"source": "ghost"}))
        data = _json(result)
        # 新结构化错误 schema：error_code=source_not_found
        assert data.get("error_code") == srv.ERROR_SOURCE_NOT_FOUND
        assert "error" not in data  # 旧字段不存在

    def test_summary_basic_shape(self, registry_with_sources):
        result = run_async(srv._handle_summary({
            "source": "test-api",
            "since": "2026-04-14T00:00:00+00:00",
        }))
        data = _json(result)
        assert set(data.keys()) >= {"total", "level_counts", "time_range", "top_messages"}
        assert data["total"] == 5
        assert data["level_counts"] == {"info": 2, "error": 2, "warning": 1}

    def test_summary_with_percentiles_and_buckets(self, registry_with_sources):
        result = run_async(srv._handle_summary({
            "source": "test-api",
            "since": "2026-04-14T00:00:00+00:00",
            "percentile_fields": ["duration_ms"],
            "bucket_interval": "1m",
        }))
        data = _json(result)
        assert "percentiles" in data
        assert "duration_ms" in data["percentiles"]
        assert set(data["percentiles"]["duration_ms"].keys()) >= {"p50", "p95", "p99"}
        assert "time_buckets" in data
        assert isinstance(data["time_buckets"], list)

    def test_summary_correlation_id_passed_to_field_filters(self, registry_with_sources, monkeypatch):
        captured = {}

        def spy(**kwargs):
            captured.update(kwargs)
            return {"time_range": [], "total": 0, "level_counts": {}, "top_messages": []}

        monkeypatch.setattr(srv, "summarize_entries", spy)
        run_async(srv._handle_summary({
            "source": "test-api",
            "correlation_id": "run-001",
        }))
        assert captured["field_filters"] == {"correlation_id": "run-001"}

    def test_cross_query_success(self, cross_sources_registry):
        result = run_async(srv._handle_cross_query({
            "sources": ["api", "client"],
            "join_field": "correlation_id",
        }))
        data = _json(result)
        assert "entries" in data
        assert len(data["entries"]) > 0

    def test_cross_query_only_one_source_returns_error_directly(self, registry_with_sources, monkeypatch):
        # 确认不会走到 engine
        called = {"cross_query": False}

        def spy(*args, **kwargs):
            called["cross_query"] = True
            return {"entries": []}

        monkeypatch.setattr(srv, "cross_query", spy)
        result = run_async(srv._handle_cross_query({
            "sources": ["test-api"],
            "join_field": "correlation_id",
        }))
        # 新结构化错误 schema：error_code=internal_error，detail 含说明
        data = _json(result)
        assert data.get("error_code") == srv.ERROR_INTERNAL
        assert "2" in data.get("detail", "") or "两" in data.get("detail", "")
        assert "error" not in data  # 旧字段不存在
        assert called["cross_query"] is False

    def test_cross_query_missing_source_wrapped(self, empty_registry):
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["ghost", "also-ghost"],
            "join_field": "correlation_id",
        }))
        data = _json(result)
        # 新结构化错误 schema：error_code=source_not_found
        assert data.get("error_code") == srv.ERROR_SOURCE_NOT_FOUND
        assert "ghost" in data.get("detail", "")
        assert "error" not in data  # 旧字段不存在


# ---------------------------------------------------------------------------
# §6 run_server Smoke
# ---------------------------------------------------------------------------

class TestRunServerSmoke:
    def test_module_import_registers_seven_tools(self):
        tools = run_async(srv.list_tools())
        assert len(tools) == 7

    def test_unknown_tool_raises_value_error(self, empty_registry):
        with pytest.raises(ValueError, match="未知 tool"):
            run_async(srv.call_tool("nonexistent_tool", {}))

    def test_run_server_without_config_path(self, monkeypatch, caplog):
        # Mock stdio_server 上下文管理器返回空 streams
        fake_read = AsyncMock()
        fake_write = AsyncMock()

        @contextlib.asynccontextmanager
        async def fake_stdio():
            yield (fake_read, fake_write)

        monkeypatch.setattr(srv, "stdio_server", fake_stdio)

        # Mock server.run 为 AsyncMock 避免真正进入事件循环
        run_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(srv.server, "run", run_mock)

        import logging
        caplog.set_level(logging.INFO, logger="log_mcp.server")

        run_async(srv.run_server(config_path=None))

        run_mock.assert_awaited_once()
        assert any("纯动态注册模式" in rec.message for rec in caplog.records)
