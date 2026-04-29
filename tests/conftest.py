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
    """
    创建两个 JSONL 源，用于跨源 UNION ALL 时间线测试。
    - frontend：有 _source 特有字段 screen（backend 无此字段）
    - backend：有 _source 特有字段 path（frontend 无此字段）
    - 近期条目（2026-04-29T10）：frontend 3 条 + backend 5 条 = 8 条
    - 远期条目（2026-04-01，超过 1h）：frontend 1 条 + backend 1 条 = 2 条
    - 总计 10 条；since=None 全量 10 条，since="2026-04-29T09:00:00+00:00" 仅近期 8 条
    注：测试不依赖 datetime.now() 以避免跨时区 CAST 问题，直接用固定时间戳。
    """
    file_fe = tmp_dir / "cross_frontend.jsonl"
    entries_fe = [
        # 近期 3 条 run-001
        {"timestamp": "2026-04-29T10:00:01+00:00", "level": "info",  "message": "page_view",     "correlation_id": "run-001", "screen": "home"},
        {"timestamp": "2026-04-29T10:00:02+00:00", "level": "info",  "message": "tap_login_btn", "correlation_id": "run-001", "screen": "login"},
        {"timestamp": "2026-04-29T10:00:03+00:00", "level": "error", "message": "login_failed",  "correlation_id": "run-001", "screen": "login"},
        # 远期 1 条（供 since 过滤测试用，since="2026-04-29T09:00:00+00:00" 时被过滤）
        {"timestamp": "2026-04-01T10:00:00+00:00", "level": "info",  "message": "old_page_view", "correlation_id": "run-001", "screen": "home"},
    ]
    with file_fe.open("w") as f:
        for e in entries_fe:
            f.write(json.dumps(e) + "\n")
    cfg_fe = {"path": str(file_fe), "rotation": "none", "format": "jsonl", "field_map": {}}

    file_be = tmp_dir / "cross_backend.jsonl"
    entries_be = [
        # 近期 5 条 run-001
        {"timestamp": "2026-04-29T10:00:01+00:00", "level": "info",  "message": "api_request",   "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-29T10:00:02+00:00", "level": "info",  "message": "db_query",      "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-29T10:00:03+00:00", "level": "info",  "message": "cache_hit",     "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-29T10:00:04+00:00", "level": "error", "message": "auth_failed",   "correlation_id": "run-001", "path": "/api/login"},
        {"timestamp": "2026-04-29T10:00:05+00:00", "level": "info",  "message": "response_sent", "correlation_id": "run-001", "path": "/api/login"},
        # 远期 1 条（供 since 过滤测试用）
        {"timestamp": "2026-04-01T10:00:00+00:00", "level": "info",  "message": "old_api_req",   "correlation_id": "run-001", "path": "/api/login"},
    ]
    with file_be.open("w") as f:
        for e in entries_be:
            f.write(json.dumps(e) + "\n")
    cfg_be = {"path": str(file_be), "rotation": "none", "format": "jsonl", "field_map": {}}

    yield {"frontend": cfg_fe, "backend": cfg_be}
    file_fe.unlink(missing_ok=True)
    file_be.unlink(missing_ok=True)


@pytest.fixture
def cross_query_4sources(tmp_dir):
    """
    构造 4 个 JSONL 源用于 token-boundary regression 测试。
    4 个源 × 每源最多 3 个参数 → 第 4 源 offset=9，$1 偏移后为 $10，
    若使用朴素字符串替换，$10 内部的 $1 会被再次替换为错误值。
    每个源各含 2 条 correlation_id="r1" + level="info" 的记录，共 8 条。
    """
    sources: dict[str, dict] = {}
    files: list[Path] = []
    for idx, svc in enumerate(["svc_a", "svc_b", "svc_c", "svc_d"]):
        filepath = tmp_dir / f"cross_4src_{svc}.jsonl"
        entries = [
            {
                "timestamp": f"2026-04-29T10:00:{idx * 10 + row:02d}+00:00",
                "level": "info",
                "message": f"{svc}_msg_{row}",
                "correlation_id": "r1",
            }
            for row in range(1, 3)
        ]
        with filepath.open("w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        sources[svc] = {
            "path": str(filepath),
            "rotation": "none",
            "format": "jsonl",
            "field_map": {},
        }
        files.append(filepath)

    yield sources

    for fp in files:
        fp.unlink(missing_ok=True)


@pytest.fixture
def cross_query_numeric_join(tmp_dir):
    """
    Regression fixture：一个源的 join_field（correlation_id）为数值类型（int），
    另一个源为字符串类型，用于验证双侧 CAST 防御：
    - numeric join_value=1 不应匹配字符串 "001"
    - string join_value="abc" 在数值 join_field 列上不抛错且返回 0 行

    源 num_src：correlation_id 存为 integer（如 1），message 为 "num_event"
    源 str_src：correlation_id 存为字符串（如 "001"），message 为 "str_event"
    """
    # 数值 correlation_id 源：使用 99 而非 1，使得 join_value=1 不匹配此源，
    # 同时也不匹配 str_src 的 "001"，从而验证 int→str CAST 防止零填充误匹配
    file_num = tmp_dir / "cross_num_join.jsonl"
    entries_num = [
        {"timestamp": "2026-04-29T10:00:01+00:00", "level": "info", "message": "num_event", "correlation_id": 99},
    ]
    with file_num.open("w") as f:
        for e in entries_num:
            f.write(json.dumps(e) + "\n")
    cfg_num = {"path": str(file_num), "rotation": "none", "format": "jsonl", "field_map": {}}

    # 字符串 correlation_id 源（"001" 与整数 1 格式不同）
    file_str = tmp_dir / "cross_str_join.jsonl"
    entries_str = [
        {"timestamp": "2026-04-29T10:00:02+00:00", "level": "info", "message": "str_event", "correlation_id": "001"},
    ]
    with file_str.open("w") as f:
        for e in entries_str:
            f.write(json.dumps(e) + "\n")
    cfg_str = {"path": str(file_str), "rotation": "none", "format": "jsonl", "field_map": {}}

    yield {"num_src": cfg_num, "str_src": cfg_str}
    file_num.unlink(missing_ok=True)
    file_str.unlink(missing_ok=True)
