import json
import shutil
import pytest
from pathlib import Path

# 测试数据目录，位于项目 tmp/（已在 .gitignore 中忽略）
TMP_DIR = Path(__file__).parent.parent / "tmp"


@pytest.fixture(scope="session", autouse=True)
def tmp_dir():
    """创建 tmp 目录，session 结束后清理。"""
    TMP_DIR.mkdir(exist_ok=True)
    yield TMP_DIR
    shutil.rmtree(TMP_DIR, ignore_errors=True)


@pytest.fixture
def jsonl_source(tmp_dir):
    """创建包含 5 条测试日志的 JSONL 文件和对应的 source_cfg。"""
    filepath = tmp_dir / "test_api.jsonl"
    entries = [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info",    "message": "http_request", "status": 200, "path": "/api/v1/login", "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 45},
        {"timestamp": "2026-04-15T10:00:02+00:00", "level": "error",   "message": "auth_failed",  "status": 500, "path": "/api/v1/auth",  "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 120},
        {"timestamp": "2026-04-15T10:00:03+00:00", "level": "info",    "message": "http_request", "status": 200, "path": "/api/v1/peers", "agent_source": "client-b", "correlation_id": "run-002", "duration_ms": 30},
        {"timestamp": "2026-04-15T10:00:04+00:00", "level": "warning", "message": "slow_query",   "status": 200, "path": "/api/v1/login", "agent_source": "client-a", "correlation_id": "run-001", "duration_ms": 800},
        {"timestamp": "2026-04-15T10:00:05+00:00", "level": "error",   "message": "db_timeout",   "status": 503, "path": "/api/v1/peers", "agent_source": "client-b", "correlation_id": "run-002", "duration_ms": 5000},
    ]
    with filepath.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    cfg = {
        "path": str(filepath),
        "rotation": "none",
        "format": "jsonl",
        "field_map": {},
    }
    yield "test-api", cfg
    filepath.unlink(missing_ok=True)


@pytest.fixture
def text_source(tmp_dir):
    """创建纯文本日志文件和对应的 source_cfg。"""
    filepath = tmp_dir / "test_plain.log"
    lines = [
        "2026-04-15 10:00:01 INFO Starting server",
        "2026-04-15 10:00:02 ERROR Connection refused",
        "2026-04-15 10:00:03 INFO Request handled",
    ]
    filepath.write_text("\n".join(lines) + "\n")
    cfg = {
        "path": str(filepath),
        "rotation": "none",
        "format": "text",
        "field_map": {},
    }
    yield "test-plain", cfg
    filepath.unlink(missing_ok=True)


@pytest.fixture
def custom_field_map_source(tmp_dir):
    """创建使用自定义字段映射的 JSONL 源。"""
    filepath = tmp_dir / "test_custom.jsonl"
    entries = [
        {"ts": "2026-04-15T10:00:01+00:00", "severity": "info",  "event": "startup"},
        {"ts": "2026-04-15T10:00:02+00:00", "severity": "error", "event": "crash"},
    ]
    with filepath.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    cfg = {
        "path": str(filepath),
        "rotation": "none",
        "format": "jsonl",
        "field_map": {"timestamp": "ts", "level": "severity", "message": "event"},
    }
    yield "test-custom", cfg
    filepath.unlink(missing_ok=True)


@pytest.fixture
def rotated_numeric_source(tmp_dir):
    """创建 numeric 轮转的日志文件集。"""
    base = tmp_dir / "rotated.jsonl"
    with base.open("w") as f:
        f.write(json.dumps({"timestamp": "2026-04-15T12:00:00+00:00", "level": "info", "message": "latest"}) + "\n")
    with (tmp_dir / "rotated.jsonl.1").open("w") as f:
        f.write(json.dumps({"timestamp": "2026-04-14T12:00:00+00:00", "level": "info", "message": "older"}) + "\n")
    cfg = {
        "path": str(base),
        "rotation": "numeric",
        "format": "jsonl",
        "field_map": {},
    }
    yield "test-rotated", cfg
    base.unlink(missing_ok=True)
    (tmp_dir / "rotated.jsonl.1").unlink(missing_ok=True)


@pytest.fixture
def cross_query_sources(tmp_dir):
    """创建两个 JSONL 源，共享 correlation_id 用于跨源关联测试。"""
    # 源 A：API 日志
    file_a = tmp_dir / "cross_api.jsonl"
    entries_a = [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info", "message": "login_request", "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-15T10:00:02+00:00", "level": "error", "message": "auth_failed", "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-15T10:00:03+00:00", "level": "info", "message": "list_peers", "correlation_id": "run-003", "path": "/api/peers"},
    ]
    with file_a.open("w") as f:
        for e in entries_a:
            f.write(json.dumps(e) + "\n")
    cfg_a = {"path": str(file_a), "rotation": "none", "format": "jsonl", "field_map": {}}

    # 源 B：客户端日志
    file_b = tmp_dir / "cross_client.jsonl"
    entries_b = [
        {"timestamp": "2026-04-15T10:00:01+00:00", "level": "info", "message": "tap_login_btn", "correlation_id": "run-001", "screen": "login"},
        {"timestamp": "2026-04-15T10:00:04+00:00", "level": "info", "message": "tap_settings", "correlation_id": "run-002", "screen": "settings"},
    ]
    with file_b.open("w") as f:
        for e in entries_b:
            f.write(json.dumps(e) + "\n")
    cfg_b = {"path": str(file_b), "rotation": "none", "format": "jsonl", "field_map": {}}

    yield {"api": cfg_a, "client": cfg_b}
    file_a.unlink(missing_ok=True)
    file_b.unlink(missing_ok=True)
