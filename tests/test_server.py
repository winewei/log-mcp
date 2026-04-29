"""
测试 log_mcp/server.py 中统一结构化错误响应 schema。

覆盖 5 类 error_code：
  source_not_found / field_not_found / time_parse_error /
  join_field_not_allowed / internal_error

以及验证旧 {"error": ...} 单字段已不存在。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest
from mcp.types import TextContent

import log_mcp.server as srv
from log_mcp.config import SourceRegistry
from log_mcp.engine import JoinFieldNotAllowed, _ALLOWED_JOIN_FIELDS


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def run_async(coro):
    """同步执行 async coroutine。"""
    return asyncio.run(coro)


def _json(result) -> dict:
    """从 list[TextContent] 中解析第一条 text 为 dict。"""
    assert isinstance(result, list) and len(result) >= 1
    assert isinstance(result[0], TextContent)
    return json.loads(result[0].text)


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_registry(monkeypatch):
    """空 registry，保证 available_sources 为 []。"""
    reg = SourceRegistry()
    monkeypatch.setattr(srv, "registry", reg)
    return reg


@pytest.fixture
def registry_with_api(tmp_path, monkeypatch):
    """注册一个含日志条目的 test-api 源。"""
    api_path = tmp_path / "api.jsonl"
    _write_jsonl(api_path, [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info", "message": "hello", "status": 200},
    ])
    reg = SourceRegistry()
    reg.register("test-api", description="API 日志", path=str(api_path))
    monkeypatch.setattr(srv, "registry", reg)
    return reg


@pytest.fixture
def two_source_registry(tmp_path, monkeypatch):
    """两个源，共享 correlation_id，用于 cross_query 场景。"""
    a_path = tmp_path / "src_a.jsonl"
    b_path = tmp_path / "src_b.jsonl"
    _write_jsonl(a_path, [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info", "message": "a", "correlation_id": "r1"},
    ])
    _write_jsonl(b_path, [
        {"timestamp": "2026-04-15T10:00:02+00:00", "level": "info", "message": "b", "correlation_id": "r1"},
    ])
    reg = SourceRegistry()
    reg.register("src-a", description="源 A", path=str(a_path))
    reg.register("src-b", description="源 B", path=str(b_path))
    monkeypatch.setattr(srv, "registry", reg)
    return reg


# ---------------------------------------------------------------------------
# 通用 schema 断言
# ---------------------------------------------------------------------------

def _assert_error_schema(data: dict, expected_code: str) -> None:
    """验证结构化错误响应包含全部必填字段且 error_code 符合预期。"""
    assert data.get("error_code") == expected_code, f"期望 error_code={expected_code!r}，实际={data}"
    assert isinstance(data.get("detail"), str) and data["detail"], "detail 必须为非空字符串"
    assert isinstance(data.get("suggestion"), str) and data["suggestion"], "suggestion 必须为非空字符串"
    assert isinstance(data.get("hints"), dict), "hints 必须为字典"
    # 旧字段不得出现
    assert "error" not in data, f"旧 'error' 字段不应存在于结构化响应中: {data}"


# ---------------------------------------------------------------------------
# Task 3.1：source_not_found 含 available_sources
# ---------------------------------------------------------------------------

class TestSourceNotFound:
    def test_query_ghost_source_returns_source_not_found(self, registry_with_api):
        """query 调用不存在的源时返回 source_not_found。"""
        result = run_async(srv.call_tool("query", {"source": "ghost"}))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_SOURCE_NOT_FOUND)
        # hints.available_sources 必须包含已注册的源
        assert "available_sources" in data["hints"]
        assert "test-api" in data["hints"]["available_sources"]

    def test_tail_ghost_source_returns_source_not_found(self, registry_with_api):
        """tail 调用不存在的源时返回 source_not_found。"""
        result = run_async(srv.call_tool("tail", {"source": "ghost"}))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_SOURCE_NOT_FOUND)
        assert "available_sources" in data["hints"]

    def test_unregister_ghost_returns_source_not_found(self, registry_with_api):
        """unregister_source 对不存在的源返回 source_not_found。"""
        result = run_async(srv.call_tool("unregister_source", {"name": "ghost"}))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_SOURCE_NOT_FOUND)
        assert "available_sources" in data["hints"]
        assert "test-api" in data["hints"]["available_sources"]

    def test_cross_query_ghost_sources_returns_source_not_found(self, registry_with_api):
        """cross_query 中存在不存在的源名时返回 source_not_found。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["ghost", "also-ghost"],
            "join_field": "correlation_id",
        }))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_SOURCE_NOT_FOUND)
        assert "available_sources" in data["hints"]

    def test_available_sources_is_empty_for_empty_registry(self, empty_registry):
        """空 registry 时 available_sources 应为空列表。"""
        result = run_async(srv.call_tool("query", {"source": "ghost"}))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_SOURCE_NOT_FOUND)
        assert data["hints"]["available_sources"] == []

    def test_suggestion_mentions_list_sources(self, empty_registry):
        """suggestion 文本应引导调用 list_sources 或 register_source。"""
        result = run_async(srv.call_tool("query", {"source": "ghost"}))
        data = _json(result)
        suggestion = data["suggestion"]
        assert "list_sources" in suggestion or "register_source" in suggestion


# ---------------------------------------------------------------------------
# Task 3.2：field_not_found 含候选字段
# ---------------------------------------------------------------------------

class TestFieldNotFound:
    def test_duckdb_binder_exception_returns_field_not_found(self, registry_with_api):
        """DuckDB BinderException 被映射为 field_not_found。"""
        # 通过 patch call_tool 内部让 engine 抛出 BinderException
        original_handler = srv._handle_query

        async def raise_binder(*args, **kwargs):
            raise duckdb.BinderException("Referenced column 'foo_field' not found")

        with patch.object(srv, "_handle_query", side_effect=raise_binder):
            result = run_async(srv.call_tool("query", {
                "source": "test-api",
                "field_filters": {"foo_field": "bar"},
            }))

        data = _json(result)
        _assert_error_schema(data, srv.ERROR_FIELD_NOT_FOUND)
        assert "candidate_fields" in data["hints"]

    def test_field_not_found_suggestion_mentions_field_map(self, registry_with_api):
        """suggestion 应提示检查 field_map 或调用 list_sources。"""
        async def raise_binder(*args, **kwargs):
            raise duckdb.BinderException("Column not found")

        with patch.object(srv, "_handle_query", side_effect=raise_binder):
            result = run_async(srv.call_tool("query", {
                "source": "test-api",
                "field_filters": {"nonexistent": "val"},
            }))

        data = _json(result)
        suggestion = data["suggestion"]
        assert "field_map" in suggestion or "list_sources" in suggestion


# ---------------------------------------------------------------------------
# Task 3.3：time_parse_error 含合法示例
# ---------------------------------------------------------------------------

class TestTimeParseError:
    def test_query_invalid_since_returns_time_parse_error(self, registry_with_api):
        """since='yesterday' 触发 ValueError，映射为 time_parse_error。"""
        result = run_async(srv.call_tool("query", {
            "source": "test-api",
            "since": "yesterday",
        }))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_TIME_PARSE_ERROR)
        # hints 必须含合法示例
        assert "valid_examples" in data["hints"]
        examples = data["hints"]["valid_examples"]
        assert isinstance(examples, list) and len(examples) > 0
        # 至少含一个相对值示例
        relative = [ex for ex in examples if any(unit in ex for unit in ("s", "m", "h", "d")) and ex[0].isdigit()]
        assert len(relative) > 0

    def test_time_parse_error_suggestion_mentions_iso8601(self, registry_with_api):
        """suggestion 应提示使用 ISO 8601 或相对值格式。"""
        result = run_async(srv.call_tool("query", {
            "source": "test-api",
            "since": "yesterday",
        }))
        data = _json(result)
        suggestion = data["suggestion"].lower()
        assert "iso" in suggestion or "8601" in suggestion or "相对" in suggestion

    def test_valid_time_examples_in_hints(self, registry_with_api):
        """hints.valid_examples 应包含 _TIME_EXAMPLES 中定义的标准示例。"""
        result = run_async(srv.call_tool("query", {
            "source": "test-api",
            "since": "not-a-time",
        }))
        data = _json(result)
        examples = data["hints"]["valid_examples"]
        # 至少包含 5m 和 1h 这类标准相对值
        assert "5m" in examples
        assert "1h" in examples


# ---------------------------------------------------------------------------
# Task 3.4：join_field_not_allowed 含白名单
# ---------------------------------------------------------------------------

class TestJoinFieldNotAllowed:
    def test_cross_query_email_field_returns_join_field_not_allowed(self, two_source_registry):
        """email 不在白名单，返回 join_field_not_allowed。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["src-a", "src-b"],
            "join_field": "email",
        }))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_JOIN_FIELD_NOT_ALLOWED)
        # hints 必须含全部白名单字段
        assert "allowed_join_fields" in data["hints"]
        allowed = set(data["hints"]["allowed_join_fields"])
        assert allowed == set(_ALLOWED_JOIN_FIELDS)

    def test_join_field_not_allowed_suggestion_mentions_whitelist(self, two_source_registry):
        """suggestion 应指明使用白名单中的字段。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["src-a", "src-b"],
            "join_field": "malicious_field",
        }))
        data = _json(result)
        suggestion = data["suggestion"]
        # suggestion 中应提及 join_field 或白名单相关信息
        assert "join_field" in suggestion or "白名单" in suggestion or "allowed" in suggestion.lower()

    def test_allowed_fields_includes_correlation_id(self, two_source_registry):
        """白名单字段 hints 中必须包含 correlation_id。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["src-a", "src-b"],
            "join_field": "email",
        }))
        data = _json(result)
        assert "correlation_id" in data["hints"]["allowed_join_fields"]


# ---------------------------------------------------------------------------
# Task 3.5：internal_error 含异常类型
# ---------------------------------------------------------------------------

class TestInternalError:
    def test_unexpected_exception_returns_internal_error(self, registry_with_api):
        """未预期异常（RuntimeError）被兜底映射为 internal_error。"""
        async def explode(*args, **kwargs):
            raise RuntimeError("模拟崩溃")

        with patch.object(srv, "_handle_query", side_effect=explode):
            result = run_async(srv.call_tool("query", {"source": "test-api"}))

        data = _json(result)
        _assert_error_schema(data, srv.ERROR_INTERNAL)
        assert "exception_type" in data["hints"]
        assert data["hints"]["exception_type"] == "RuntimeError"

    def test_internal_error_process_does_not_crash(self, registry_with_api):
        """internal_error 下进程不崩溃，能继续处理后续请求。"""
        async def explode(*args, **kwargs):
            raise Exception("随机崩溃")

        with patch.object(srv, "_handle_query", side_effect=explode):
            result1 = run_async(srv.call_tool("query", {"source": "test-api"}))
        # 进程未崩溃，可以继续调用
        result2 = run_async(srv.call_tool("list_sources", {}))
        data2 = _json(result2)
        assert isinstance(data2, list)

    def test_cross_query_fewer_than_two_returns_internal_error(self, registry_with_api):
        """cross_query sources < 2 时返回 internal_error 且说明原因。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["test-api"],
            "join_field": "correlation_id",
        }))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_INTERNAL)
        assert "2" in data["detail"] or "两" in data["detail"] or "least" in data["detail"]

    def test_register_source_invalid_format_returns_internal_error(self, empty_registry, tmp_path):
        """register_source 参数校验失败时返回 internal_error。"""
        log = tmp_path / "x.jsonl"
        log.touch()
        result = run_async(srv.call_tool("register_source", {
            "name": "bad",
            "description": "desc",
            "path": str(log),
            "format": "invalid",
        }))
        data = _json(result)
        _assert_error_schema(data, srv.ERROR_INTERNAL)
        assert "exception_type" in data["hints"]


# ---------------------------------------------------------------------------
# Task 3.6：旧 {"error": ...} 字段已不存在
# ---------------------------------------------------------------------------

class TestNoLegacyErrorField:
    def test_source_not_found_has_no_legacy_error(self, empty_registry):
        """source_not_found 响应中不含旧 'error' 字段。"""
        result = run_async(srv.call_tool("query", {"source": "ghost"}))
        data = _json(result)
        assert "error" not in data

    def test_time_parse_error_has_no_legacy_error(self, registry_with_api):
        """time_parse_error 响应中不含旧 'error' 字段。"""
        result = run_async(srv.call_tool("query", {
            "source": "test-api",
            "since": "yesterday",
        }))
        data = _json(result)
        assert "error" not in data

    def test_join_field_not_allowed_has_no_legacy_error(self, two_source_registry):
        """join_field_not_allowed 响应中不含旧 'error' 字段。"""
        result = run_async(srv.call_tool("cross_query", {
            "sources": ["src-a", "src-b"],
            "join_field": "email",
        }))
        data = _json(result)
        assert "error" not in data

    def test_internal_error_has_no_legacy_error(self, registry_with_api):
        """internal_error 响应中不含旧 'error' 字段。"""
        async def explode(*args, **kwargs):
            raise RuntimeError("崩溃")

        with patch.object(srv, "_handle_query", side_effect=explode):
            result = run_async(srv.call_tool("query", {"source": "test-api"}))
        data = _json(result)
        assert "error" not in data

    def test_unregister_not_found_has_no_legacy_error(self, empty_registry):
        """unregister 不存在的源响应中不含旧 'error' 字段。"""
        result = run_async(srv.call_tool("unregister_source", {"name": "ghost"}))
        data = _json(result)
        assert "error" not in data
