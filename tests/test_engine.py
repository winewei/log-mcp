import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from log_mcp.engine import (
    cross_query,
    discover_files,
    query_entries,
    tail_entries,
    summarize_entries,
    _parse_time,
    _parse_filter_expr,
)

# ---------------------------------------------------------------------------
# TestDiscoverFiles
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_numeric_rotation(self, tmp_path):
        # 主文件 + .1 文件均应被发现
        main = tmp_path / "app.log"
        rotated = tmp_path / "app.log.1"
        main.touch()
        rotated.touch()
        files = discover_files(str(main), "numeric")
        assert main in files
        assert rotated in files
        assert len(files) == 2

    def test_date_rotation(self, tmp_path):
        # 日期命名的轮转文件应被发现，且主文件排在首位
        main = tmp_path / "app.log"
        dated = tmp_path / "app.2026-04-14.log"
        main.touch()
        dated.touch()
        files = discover_files(str(main), "date")
        assert main in files
        assert dated in files
        assert files[0] == main  # 主文件排首位

    def test_none_rotation(self, tmp_path):
        # rotation=none 只返回主文件
        main = tmp_path / "app.log"
        extra = tmp_path / "app.log.1"
        main.touch()
        extra.touch()
        files = discover_files(str(main), "none")
        assert files == [main]

    def test_missing_file(self, tmp_path):
        # 文件不存在时返回空列表
        missing = tmp_path / "nonexistent.log"
        files = discover_files(str(missing), "none")
        assert files == []


# ---------------------------------------------------------------------------
# TestParseTime
# ---------------------------------------------------------------------------

class TestParseTime:
    def test_iso_8601(self):
        # ISO 格式直接解析后返回，时区信息保留
        result = _parse_time("2026-04-15T10:00:00+00:00")
        assert "2026-04-15" in result

    def test_relative_seconds(self):
        # "30s" 应转为约 30 秒前的绝对时间
        before = datetime.now(timezone.utc) - timedelta(seconds=31)
        after = datetime.now(timezone.utc) - timedelta(seconds=29)
        result = _parse_time("30s")
        dt = datetime.fromisoformat(result)
        assert before <= dt <= after

    def test_relative_minutes(self):
        # "5m" 转为约 5 分钟前的绝对时间
        before = datetime.now(timezone.utc) - timedelta(minutes=5, seconds=1)
        after = datetime.now(timezone.utc) - timedelta(minutes=4, seconds=59)
        result = _parse_time("5m")
        dt = datetime.fromisoformat(result)
        assert before <= dt <= after

    def test_relative_hours(self):
        # "1h" 转为约 1 小时前的绝对时间
        before = datetime.now(timezone.utc) - timedelta(hours=1, seconds=1)
        after = datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(seconds=1)
        result = _parse_time("1h")
        dt = datetime.fromisoformat(result)
        assert before <= dt <= after

    def test_relative_days(self):
        # "1d" 转为约 1 天前的绝对时间
        before = datetime.now(timezone.utc) - timedelta(days=1, seconds=1)
        after = datetime.now(timezone.utc) - timedelta(days=1) + timedelta(seconds=1)
        result = _parse_time("1d")
        dt = datetime.fromisoformat(result)
        assert before <= dt <= after

    def test_invalid_expr(self):
        # 无效表达式应抛出 ValueError
        with pytest.raises(ValueError):
            _parse_time("not-a-time")


# ---------------------------------------------------------------------------
# TestParseFilterExpr
# ---------------------------------------------------------------------------

class TestParseFilterExpr:
    def test_exact_match(self):
        # 默认精确匹配，生成 CAST = $N 形式的 SQL
        params: list = []
        sql = _parse_filter_expr("status", "200", params)
        assert "=" in sql
        assert params == ["200"]

    def test_regex_match(self):
        # ~ 前缀触发 regexp_matches
        params: list = []
        sql = _parse_filter_expr("path", "~/api/v1", params)
        assert "regexp_matches" in sql
        assert params == ["/api/v1"]

    def test_gte(self):
        # >= 触发数值大于等于比较
        params: list = []
        sql = _parse_filter_expr("duration_ms", ">=100", params)
        assert ">=" in sql
        assert params == [100.0]

    def test_lte(self):
        # <= 触发数值小于等于比较
        params: list = []
        sql = _parse_filter_expr("duration_ms", "<=500", params)
        assert "<=" in sql
        assert params == [500.0]

    def test_gt(self):
        # > 触发数值大于比较（注意不能误匹配 >=）
        params: list = []
        sql = _parse_filter_expr("status", ">400", params)
        assert ">=" not in sql
        assert ">" in sql
        assert params == [400.0]

    def test_lt(self):
        # < 触发数值小于比较
        params: list = []
        sql = _parse_filter_expr("status", "<300", params)
        assert "<=" not in sql
        assert "<" in sql
        assert params == [300.0]

    def test_not_equal(self):
        # ! 前缀触发不等于条件
        params: list = []
        sql = _parse_filter_expr("level", "!debug", params)
        assert "!=" in sql
        assert params == ["debug"]


# ---------------------------------------------------------------------------
# TestQueryEntries
# ---------------------------------------------------------------------------

class TestQueryEntries:
    def test_basic_query(self, jsonl_source):
        # 无过滤条件返回全部 5 条
        name, cfg = jsonl_source
        result = query_entries(name, cfg)
        assert result["total_matched"] == 5
        assert len(result["entries"]) == 5

    def test_level_filter(self, jsonl_source):
        # level=error 命中 2 条：auth_failed 和 db_timeout
        name, cfg = jsonl_source
        result = query_entries(name, cfg, level="error")
        assert result["total_matched"] == 2
        messages = {e["_message"] for e in result["entries"]}
        assert messages == {"auth_failed", "db_timeout"}

    def test_message_pattern(self, jsonl_source):
        # 正则匹配 "http_" 命中 2 条 http_request
        name, cfg = jsonl_source
        result = query_entries(name, cfg, message_pattern="http_")
        assert result["total_matched"] == 2

    def test_field_filter_exact(self, jsonl_source):
        # agent_source 精确匹配 client-a，命中 3 条
        name, cfg = jsonl_source
        result = query_entries(name, cfg, field_filters={"agent_source": "client-a"})
        assert result["total_matched"] == 3

    def test_field_filter_regex(self, jsonl_source):
        # path 正则匹配 /login，命中 2 条
        name, cfg = jsonl_source
        result = query_entries(name, cfg, field_filters={"path": "~/login"})
        assert result["total_matched"] == 2

    def test_field_filter_numeric(self, jsonl_source):
        # status>=400 命中 error 条目（500 和 503）
        name, cfg = jsonl_source
        result = query_entries(name, cfg, field_filters={"status": ">=400"})
        assert result["total_matched"] == 2

    def test_field_filter_not(self, jsonl_source):
        # agent_source 取反，排除 client-a，剩余 2 条 client-b
        name, cfg = jsonl_source
        result = query_entries(name, cfg, field_filters={"agent_source": "!client-a"})
        assert result["total_matched"] == 2

    def test_limit(self, jsonl_source):
        # limit=2 截断为 2 条，但 total_matched 仍为 5
        name, cfg = jsonl_source
        result = query_entries(name, cfg, limit=2)
        assert result["total_matched"] == 5
        assert len(result["entries"]) == 2

    def test_order_asc(self, jsonl_source):
        # 结果应按 _timestamp ASC 排序，第一条时间早于最后一条
        name, cfg = jsonl_source
        result = query_entries(name, cfg)
        entries = result["entries"]
        assert entries[0]["_timestamp"] <= entries[-1]["_timestamp"]

    def test_source_field(self, jsonl_source):
        # 每条记录应包含 _source 字段，值为 source_name
        name, cfg = jsonl_source
        result = query_entries(name, cfg)
        for entry in result["entries"]:
            assert entry["_source"] == name

    def test_offset_pagination(self, jsonl_source):
        # offset=2, limit=2 应返回第 3~4 条记录
        name, cfg = jsonl_source
        result = query_entries(name, cfg, limit=2, offset=2)
        assert result["total_matched"] == 5
        assert len(result["entries"]) == 2
        # 第一页
        page1 = query_entries(name, cfg, limit=2, offset=0)
        # 第二页不应与第一页重叠
        page1_ts = {str(e["_timestamp"]) for e in page1["entries"]}
        page2_ts = {str(e["_timestamp"]) for e in result["entries"]}
        assert page1_ts.isdisjoint(page2_ts)

    def test_offset_beyond_total(self, jsonl_source):
        # offset 超出总数时返回空列表
        name, cfg = jsonl_source
        result = query_entries(name, cfg, offset=100)
        assert result["total_matched"] == 5
        assert len(result["entries"]) == 0

    def test_empty_files(self, tmp_path):
        # 文件不存在时返回空结果结构
        cfg = {
            "path": str(tmp_path / "nonexistent.jsonl"),
            "rotation": "none",
            "format": "jsonl",
            "field_map": {},
        }
        result = query_entries("empty", cfg)
        assert result == {"total_matched": 0, "entries": []}


# ---------------------------------------------------------------------------
# TestTailEntries
# ---------------------------------------------------------------------------

class TestTailEntries:
    def test_basic_tail(self, jsonl_source):
        # 返回最新 3 条
        name, cfg = jsonl_source
        result = tail_entries(name, cfg, count=3)
        assert len(result["entries"]) == 3

    def test_tail_order_desc(self, jsonl_source):
        # 结果应按 _timestamp DESC 排序，第一条时间晚于最后一条
        name, cfg = jsonl_source
        result = tail_entries(name, cfg, count=5)
        entries = result["entries"]
        assert entries[0]["_timestamp"] >= entries[-1]["_timestamp"]

    def test_tail_with_level(self, jsonl_source):
        # tail + level=error 只返回 error 级别
        name, cfg = jsonl_source
        result = tail_entries(name, cfg, count=10, level="error")
        assert result["total_matched"] == 2
        for entry in result["entries"]:
            assert entry["_level"] == "error"


# ---------------------------------------------------------------------------
# TestSummarizeEntries
# ---------------------------------------------------------------------------

class TestSummarizeEntries:
    def test_basic_summary(self, jsonl_source):
        # 验证 total、level_counts、time_range、top_messages 均存在且合理
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None)
        assert result["total"] == 5
        assert "error" in result["level_counts"]
        assert result["level_counts"]["error"] == 2
        assert len(result["time_range"]) == 2
        assert len(result["top_messages"]) > 0

    def test_group_by(self, jsonl_source):
        # group_by=agent_source 应返回 groups 字段，含 client-a 和 client-b
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None, group_by="agent_source")
        assert "groups" in result
        assert "client-a" in result["groups"]
        assert "client-b" in result["groups"]
        # client-a 有 1 条 error
        assert result["groups"]["client-a"]["errors"] == 1

    def test_percentile_fields(self, jsonl_source):
        # percentile_fields=["duration_ms"] 应返回 p50/p95/p99
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None, percentile_fields=["duration_ms"])
        assert "percentiles" in result
        assert "duration_ms" in result["percentiles"]
        pct = result["percentiles"]["duration_ms"]
        assert "p50" in pct and "p95" in pct and "p99" in pct
        assert pct["p50"] <= pct["p95"] <= pct["p99"]

    def test_percentile_fields_omitted(self, jsonl_source):
        # 不传 percentile_fields 时结果中不应有 percentiles 字段
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None)
        assert "percentiles" not in result

    def test_bucket_interval(self, jsonl_source):
        # bucket_interval="1m" 应返回 time_buckets 数组
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None, bucket_interval="1m")
        assert "time_buckets" in result
        buckets = result["time_buckets"]
        assert len(buckets) >= 1
        for b in buckets:
            assert "bucket" in b and "total" in b and "errors" in b

    def test_bucket_interval_omitted(self, jsonl_source):
        # 不传 bucket_interval 时结果中不应有 time_buckets 字段
        name, cfg = jsonl_source
        result = summarize_entries(name, cfg, since=None)
        assert "time_buckets" not in result

    def test_empty_source(self, tmp_path):
        # 空源（文件不存在）应返回零值结构
        cfg = {
            "path": str(tmp_path / "nonexistent.jsonl"),
            "rotation": "none",
            "format": "jsonl",
            "field_map": {},
        }
        result = summarize_entries("empty", cfg, since=None)
        assert result["total"] == 0
        assert result["level_counts"] == {}
        assert result["top_messages"] == []
        assert result["time_range"] == []


# ---------------------------------------------------------------------------
# TestCustomFieldMap
# ---------------------------------------------------------------------------

class TestCustomFieldMap:
    def test_field_map_normalization(self, custom_field_map_source):
        # ts→_timestamp、severity→_level、event→_message 映射应正确归一化
        name, cfg = custom_field_map_source
        result = query_entries(name, cfg)
        assert result["total_matched"] == 2
        entry = result["entries"][0]
        # 归一化字段必须存在
        assert "_timestamp" in entry
        assert "_level" in entry
        assert "_message" in entry
        # 值应来自原始自定义字段
        assert entry["_level"] in ("info", "error")
        assert entry["_message"] in ("startup", "crash")


# ---------------------------------------------------------------------------
# TestTextFormat
# ---------------------------------------------------------------------------

class TestTextFormat:
    def test_text_query(self, text_source):
        # text 格式应能正常查询，返回 3 条（_timestamp 为 NULL）
        name, cfg = text_source
        result = query_entries(name, cfg)
        assert result["total_matched"] == 3
        for entry in result["entries"]:
            assert "_message" in entry
            assert "_source" in entry

    def test_text_message_pattern(self, text_source):
        # text 格式支持 message_pattern 正则匹配
        name, cfg = text_source
        result = query_entries(name, cfg, message_pattern="ERROR")
        assert result["total_matched"] == 1
        assert "ERROR" in result["entries"][0]["_message"]


# ---------------------------------------------------------------------------
# TestNumericRotation
# ---------------------------------------------------------------------------

class TestNumericRotation:
    def test_rotated_files_combined(self, rotated_numeric_source):
        # 主文件与 .1 轮转文件应合并查询，返回 2 条
        name, cfg = rotated_numeric_source
        result = query_entries(name, cfg)
        assert result["total_matched"] == 2
        messages = {e["_message"] for e in result["entries"]}
        assert "latest" in messages
        assert "older" in messages


# ---------------------------------------------------------------------------
# TestCrossQuery
# ---------------------------------------------------------------------------

class TestCrossQuery:
    def test_basic_cross_query(self, cross_query_sources):
        # run-001 在两个源中都存在，INNER JOIN 应命中
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
        )
        assert "entries" in result
        # api 源有 2 条 run-001，client 源有 1 条 run-001
        # INNER JOIN 应产生 2 条结果（api 的 2 条 x client 的 1 条匹配）
        assert len(result["entries"]) >= 1

    def test_inner_join_semantics(self, cross_query_sources):
        # run-003 仅在 api 中存在，run-002 仅在 client 中存在，均不应出现
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
        )
        corr_ids = {str(e.get("correlation_id")) for e in result["entries"]}
        assert "run-003" not in corr_ids
        assert "run-002" not in corr_ids

    def test_invalid_join_field(self, cross_query_sources):
        # 非白名单字段应返回错误
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="malicious_field",
        )
        assert "error" in result

    def test_cross_query_with_level(self, cross_query_sources):
        # level=error 过滤后，只有 api 的 auth_failed 满足
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            level="error",
        )
        for e in result["entries"]:
            assert e["_level"] == "error"
