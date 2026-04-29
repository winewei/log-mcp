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
    _project_fields,
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
# TestCrossQuery（UNION ALL BY NAME 时间线语义）
# ---------------------------------------------------------------------------

class TestCrossQuery:
    def test_row_count_equals_sum_of_sources(self, cross_query_sources):
        # UNION ALL 语义：frontend 4 条 + backend 6 条 = 10 条（全量，since=None）
        # 旧 INNER JOIN 语义会产生笛卡尔积，此测试验证新语义为各源之和
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        assert "entries" in result
        # frontend 4 条 + backend 6 条
        assert len(result["entries"]) == 10

    def test_source_field_present_in_all_entries(self, cross_query_sources):
        # 每条 entry 均含 _source 字段，标识其来源（由 _normalize_select 注入）
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        for entry in result["entries"]:
            assert "_source" in entry
            assert entry["_source"] in ("frontend", "backend")

    def test_source_field_values_cover_both_sources(self, cross_query_sources):
        # _source 字段取值涵盖两个源名
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        sources_present = {e["_source"] for e in result["entries"]}
        assert "frontend" in sources_present
        assert "backend" in sources_present

    def test_ordered_by_timestamp_asc(self, cross_query_sources):
        # 结果按 _timestamp ASC 排序（时间线语义）
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        entries = result["entries"]
        timestamps = [str(e["_timestamp"]) for e in entries if e.get("_timestamp")]
        assert timestamps == sorted(timestamps)

    def test_union_by_name_null_alignment(self, cross_query_sources):
        # frontend 有 screen 字段，backend 有 path 字段
        # UNION ALL BY NAME 后：frontend 行的 path 为 NULL，backend 行的 screen 为 NULL
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        entries = result["entries"]
        fe_entries = [e for e in entries if e["_source"] == "frontend"]
        be_entries = [e for e in entries if e["_source"] == "backend"]

        # frontend 行含 screen 字段（非 NULL），path 字段缺失或为 NULL
        assert len(fe_entries) > 0
        for e in fe_entries:
            assert e.get("screen") is not None
            # backend 特有字段 path 应补 NULL
            assert e.get("path") is None

        # backend 行含 path 字段（非 NULL），screen 字段缺失或为 NULL
        assert len(be_entries) > 0
        for e in be_entries:
            assert e.get("path") is not None
            # frontend 特有字段 screen 应补 NULL
            assert e.get("screen") is None

    def test_since_filter_excludes_old_entries(self, cross_query_sources):
        # 使用 since="2026-04-29T09:00:00+00:00" 过滤远期条目（2026-04-01）
        # 近期：frontend 3 条 + backend 5 条 = 8 条；远期 2 条被过滤
        cfgs = cross_query_sources
        result_filtered = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since="2026-04-29T09:00:00+00:00",
        )
        result_all = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        # 过滤后条数 < 全量
        assert len(result_filtered["entries"]) < len(result_all["entries"])
        # 远期条目不应出现
        for entry in result_filtered["entries"]:
            assert entry.get("_message") != "old_page_view"
            assert entry.get("_message") != "old_api_req"

    def test_since_explicit_none_includes_all_entries(self, cross_query_sources):
        # 显式传 since=None 时应全量扫描，返回 10 条（frontend 4 + backend 6）
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
        )
        assert len(result["entries"]) == 10

    def test_fields_whitelist(self, cross_query_sources):
        # fields 参数生效：仅返回指定字段
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
            fields=["_timestamp", "_source", "_message"],
        )
        for entry in result["entries"]:
            assert set(entry.keys()) == {"_timestamp", "_source", "_message"}

    def test_invalid_join_field_raises(self, cross_query_sources):
        # 非白名单字段应抛出 JoinFieldNotAllowed（由 engine 层 raise，server 层捕获映射）
        from log_mcp.engine import JoinFieldNotAllowed
        cfgs = cross_query_sources
        with pytest.raises(JoinFieldNotAllowed):
            cross_query(
                sources_cfg=cfgs,
                join_field="malicious_field",
            )

    def test_level_filter_applies_to_all_sources(self, cross_query_sources):
        # level=error 过滤后，所有返回 entry 的 _level 均为 error
        cfgs = cross_query_sources
        result = cross_query(
            sources_cfg=cfgs,
            join_field="correlation_id",
            since=None,
            level="error",
        )
        assert len(result["entries"]) > 0
        for e in result["entries"]:
            assert e["_level"] == "error"

    def test_fewer_than_two_sources_raises(self, cross_query_sources):
        # 少于 2 个 source 抛 ValueError
        cfgs = cross_query_sources
        single = {"frontend": cfgs["frontend"]}
        with pytest.raises(ValueError, match="至少需要 2"):
            cross_query(sources_cfg=single, join_field="correlation_id")


# ---------------------------------------------------------------------------
# TestProjectFields：字段裁剪与白名单
# ---------------------------------------------------------------------------

class TestProjectFields:
    def _make_row(self, extra: dict | None = None) -> dict:
        """构造一条包含归一化字段的基础 row。"""
        row = {
            "_timestamp": "2026-04-15T10:00:01+00:00",
            "_level": "info",
            "_message": "hello",
            "_source": "test",
        }
        if extra:
            row.update(extra)
        return row

    def test_default_truncation_large_field(self):
        # 4.1 默认裁剪：单字段 100KB 被替换为 <truncated:100.0KB>
        large_value = "x" * (100 * 1024)  # 100KB 纯 ASCII
        row = self._make_row({"body": large_value})
        result = _project_fields([row], fields=None)
        assert len(result) == 1
        entry = result[0]
        assert entry["body"] == "<truncated:100.0KB>"

    def test_whitelist_returns_only_specified_fields(self, jsonl_source):
        # 4.2 白名单：传 fields=["_timestamp","_message"] 仅返回两字段
        name, cfg = jsonl_source
        result = query_entries(name, cfg, fields=["_timestamp", "_message"])
        for entry in result["entries"]:
            assert set(entry.keys()) == {"_timestamp", "_message"}

    def test_whitelist_large_field_not_truncated(self):
        # 4.3 白名单内大字段不被截断，原值返回
        large_value = "y" * (200 * 1024)  # 200KB
        row = self._make_row({"body": large_value})
        result = _project_fields([row], fields=["body"])
        assert len(result) == 1
        # 白名单字段原值返回，不截断
        assert result[0]["body"] == large_value

    def test_whitelist_nonexistent_field_returns_none(self):
        # 4.4 fields 含不存在字段时返回 None 不报错
        row = self._make_row()
        result = _project_fields([row], fields=["nonexistent"])
        assert len(result) == 1
        assert result[0]["nonexistent"] is None

    def test_normalized_timestamp_preserved_in_default_mode(self):
        # 4.5 _timestamp 字段无论多大都保留原值（归一化字段不参与截断）
        # _timestamp 理论上不会超 4KB，但此处验证其在归一化集合中不被截断
        large_ts = "T" * (10 * 1024)  # 超出 4KB 的模拟时间戳字符串
        row = {
            "_timestamp": large_ts,
            "_level": "info",
            "_message": "test",
            "_source": "test",
        }
        result = _project_fields([row], fields=None)
        assert len(result) == 1
        # 归一化字段 _timestamp 原值返回，不被截断
        assert result[0]["_timestamp"] == large_ts
