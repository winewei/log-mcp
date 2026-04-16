"""
tests/test_config.py
覆盖 log_mcp/config.py 中 _validate_source、load_config、SourceRegistry 的全部公开契约。
"""

from pathlib import Path

import pytest
import yaml

from log_mcp.config import (
    SourceRegistry,
    _validate_source,
    load_config,
)

# ---------------------------------------------------------------------------
# Section 1 — 脚手架 helper（任务 1.1 / 1.2）
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, data: dict, filename: str = "sources.yaml"):
    """
    1.1 helper：接收任意 dict，写入临时 yaml 文件，返回文件绝对路径字符串。
    使用 pytest 内建 tmp_path，不落进仓库。
    """
    p = tmp_path / filename
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return str(p)


def _minimal_yaml_path(tmp_path, filename: str = "minimal.yaml"):
    """
    1.2 helper：写入最小合法 yaml（sources 为空 dict），返回路径字符串。
    供 SourceRegistry 持久化场景使用。
    """
    return _write_yaml(tmp_path, {"sources": {}}, filename)


# ---------------------------------------------------------------------------
# Section 2 — _validate_source 单元测试
# ---------------------------------------------------------------------------


class TestValidateSource:
    """覆盖 _validate_source 的 7 个测试点（任务 2.1 ~ 2.7）。"""

    # 最小合法输入，各测试按需覆盖
    _BASE = {
        "description": "测试源",
        "path": "/tmp/app.log",
    }

    def _cfg(self, **overrides):
        """从最小合法输入出发，叠加覆盖字段。"""
        return {**self._BASE, **overrides}

    def test_missing_description_raises_value_error(self):
        """2.1 缺少 description → ValueError。"""
        with pytest.raises(ValueError, match="description"):
            _validate_source("src", {"path": "/tmp/app.log"})

    def test_empty_description_raises_value_error(self):
        """2.1 description 为空字符串 → ValueError。"""
        with pytest.raises(ValueError, match="description"):
            _validate_source("src", self._cfg(description=""))

    def test_missing_path_raises_value_error(self):
        """2.2 缺少 path → ValueError。"""
        with pytest.raises(ValueError, match="path"):
            _validate_source("src", {"description": "测试源"})

    def test_empty_path_raises_value_error(self):
        """2.2 path 为空字符串 → ValueError。"""
        with pytest.raises(ValueError, match="path"):
            _validate_source("src", self._cfg(path=""))

    def test_invalid_rotation_raises_value_error(self):
        """2.3 非法 rotation（"weekly"）→ ValueError。"""
        with pytest.raises(ValueError, match="rotation"):
            _validate_source("src", self._cfg(rotation="weekly"))

    def test_invalid_format_raises_value_error(self):
        """2.4 非法 format（"xml"）→ ValueError。"""
        with pytest.raises(ValueError, match="format"):
            _validate_source("src", self._cfg(format="xml"))

    def test_field_map_absent_defaults_to_empty_dict(self):
        """2.5 field_map 缺省 → 返回 dict 中 field_map 为空 dict，不抛错。"""
        result = _validate_source("src", self._cfg())
        assert result["field_map"] == {}

    def test_field_map_with_invalid_key_raises_value_error(self):
        """2.6 field_map 含非法键 → ValueError。"""
        with pytest.raises(ValueError, match="field_map"):
            _validate_source("src", self._cfg(field_map={"ts": "timestamp", "extra": "x"}))

    def test_valid_full_input_returns_normalized_dict(self):
        """2.7 完整合法输入 → 返回包含五个标准化字段的 dict。"""
        result = _validate_source(
            "src",
            {
                "description": "完整源",
                "path": "/var/log/app.jsonl",
                "rotation": "date",
                "format": "text",
                "field_map": {"timestamp": "ts", "level": "sev"},
            },
        )
        assert result["description"] == "完整源"
        assert result["path"] == "/var/log/app.jsonl"
        assert result["rotation"] == "date"
        assert result["format"] == "text"
        assert result["field_map"] == {"timestamp": "ts", "level": "sev"}


# ---------------------------------------------------------------------------
# Section 3 — load_config 单元测试
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """覆盖 load_config 的 6 个测试点（任务 3.1 ~ 3.6）。"""

    def test_nonexistent_path_raises_file_not_found(self, tmp_path):
        """3.1 路径不存在 → FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "does_not_exist.yaml"))

    def test_yaml_syntax_error_raises_yaml_error(self, tmp_path):
        """3.2 YAML 语法错误 → yaml.YAMLError。"""
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : :", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_config(str(bad))

    def test_sources_as_list_raises_value_error(self, tmp_path):
        """3.3 顶层 sources 为列表而非对象 → ValueError。"""
        p = _write_yaml(tmp_path, {"sources": [{"name": "a"}]})
        with pytest.raises(ValueError, match="sources"):
            load_config(p)

    def test_empty_file_returns_empty_dict(self, tmp_path):
        """3.4a 空文件 → 返回空 dict，不抛错。"""
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        result = load_config(str(empty))
        assert result == {}

    def test_missing_sources_key_returns_empty_dict(self, tmp_path):
        """3.4b 无 sources 键 → 返回空 dict。"""
        p = _write_yaml(tmp_path, {"other_key": "value"})
        result = load_config(p)
        assert result == {}

    def test_multiple_sources_loaded_correctly(self, tmp_path):
        """3.5 多源正常加载 → 返回 dict，key 为源名，value 是标准化 cfg。"""
        data = {
            "sources": {
                "api": {
                    "description": "API 日志",
                    "path": "/tmp/api.jsonl",
                    "rotation": "numeric",
                    "format": "jsonl",
                },
                "db": {
                    "description": "DB 日志",
                    "path": "/tmp/db.jsonl",
                    "rotation": "none",
                    "format": "jsonl",
                },
            }
        }
        p = _write_yaml(tmp_path, data)
        result = load_config(p)
        assert set(result.keys()) == {"api", "db"}
        assert result["api"]["description"] == "API 日志"
        assert result["db"]["rotation"] == "none"
        # field_map 缺省应为空 dict
        assert result["api"]["field_map"] == {}

    def test_invalid_source_bubbles_value_error(self, tmp_path):
        """3.6 某源字段非法 → 冒泡 ValueError。"""
        data = {
            "sources": {
                "bad_src": {
                    "description": "非法格式源",
                    "path": "/tmp/x.log",
                    "format": "xml",  # 非法
                }
            }
        }
        p = _write_yaml(tmp_path, data)
        with pytest.raises(ValueError, match="format"):
            load_config(p)


# ---------------------------------------------------------------------------
# Section 4 — SourceRegistry 纯内存行为测试
# ---------------------------------------------------------------------------


class TestSourceRegistryMemory:
    """覆盖 SourceRegistry 纯内存操作的 8 个测试点（任务 4.1 ~ 4.8）。"""

    def _make_registry(self):
        return SourceRegistry()

    def _valid_register_kwargs(self, path: str = "/tmp/app.jsonl"):
        return dict(description="测试源", path=path)

    def test_load_from_file_merges_into_empty_registry(self, tmp_path):
        """4.1 load_from_file 把 YAML 源合并进空 Registry。"""
        data = {
            "sources": {
                "svc": {
                    "description": "服务日志",
                    "path": "/tmp/svc.jsonl",
                }
            }
        }
        p = _write_yaml(tmp_path, data)
        reg = self._make_registry()
        reg.load_from_file(p)
        assert "svc" in reg.list()
        assert reg.get("svc")["description"] == "服务日志"

    def test_load_from_file_overwrites_same_name_memory_source(self, tmp_path):
        """4.2 load_from_file 遇同名内存源时覆盖。"""
        reg = self._make_registry()
        # 先内存注册一个 "svc"
        reg.register("svc", description="旧描述", path="/tmp/old.jsonl")
        # YAML 中有同名 "svc" 但内容不同
        data = {
            "sources": {
                "svc": {
                    "description": "新描述",
                    "path": "/tmp/new.jsonl",
                }
            }
        }
        p = _write_yaml(tmp_path, data)
        reg.load_from_file(p)
        assert reg.get("svc")["description"] == "新描述"
        assert reg.get("svc")["path"] == "/tmp/new.jsonl"

    def test_register_then_get_and_list(self):
        """4.3 register 后 get/list 均可见。"""
        reg = self._make_registry()
        reg.register("api", description="API 日志", path="/tmp/api.jsonl")
        cfg = reg.get("api")
        assert cfg["description"] == "API 日志"
        assert "api" in reg.list()

    def test_register_overwrite_same_name(self):
        """4.4 同名源二次 register 直接覆盖，不抛错。"""
        reg = self._make_registry()
        reg.register("api", description="旧", path="/tmp/a.jsonl")
        reg.register("api", description="新", path="/tmp/b.jsonl")
        assert reg.get("api")["description"] == "新"
        assert reg.get("api")["path"] == "/tmp/b.jsonl"

    def test_unregister_existing_source(self):
        """4.5 unregister 对已存在源移除成功。"""
        reg = self._make_registry()
        reg.register("api", description="API 日志", path="/tmp/api.jsonl")
        reg.unregister("api")
        assert "api" not in reg.list()

    def test_unregister_nonexistent_raises_key_error(self):
        """4.6 unregister 不存在的源 → KeyError。"""
        reg = self._make_registry()
        with pytest.raises(KeyError):
            reg.unregister("ghost")

    def test_get_nonexistent_raises_key_error(self):
        """4.7 get 不存在的源 → KeyError。"""
        reg = self._make_registry()
        with pytest.raises(KeyError):
            reg.get("ghost")

    def test_list_returns_shallow_copy(self):
        """4.8 list() 返回浅拷贝，修改返回值不影响内部状态。"""
        reg = self._make_registry()
        reg.register("api", description="API 日志", path="/tmp/api.jsonl")
        snapshot = reg.list()
        # 直接删除返回字典中的键
        del snapshot["api"]
        # 内部状态不受影响
        assert "api" in reg.list()


# ---------------------------------------------------------------------------
# Section 5 — SourceRegistry 持久化路径
# ---------------------------------------------------------------------------


class TestSourceRegistryPersist:
    """覆盖持久化操作的 6 个测试点（任务 5.1 ~ 5.6）。"""

    def test_register_persist_without_config_path_raises_runtime_error(self):
        """5.1 无 config_path 的 Registry，register(persist=True) → RuntimeError。"""
        reg = SourceRegistry()
        with pytest.raises(RuntimeError, match="config_path"):
            reg.register("api", description="API 日志", path="/tmp/api.jsonl", persist=True)

    def test_unregister_persist_without_config_path_raises_runtime_error(self):
        """5.2 无 config_path 的 Registry，unregister(persist=True) → RuntimeError。"""
        reg = SourceRegistry()
        # 先内存注册，确保 name 存在
        reg.register("api", description="API 日志", path="/tmp/api.jsonl")
        with pytest.raises(RuntimeError, match="config_path"):
            reg.unregister("api", persist=True)

    def test_register_persist_creates_yaml_when_file_missing(self, tmp_path):
        """5.3 config_path 不存在时 register(persist=True) 自动创建文件并写入源。"""
        yaml_path = str(tmp_path / "auto_created.yaml")
        reg = SourceRegistry(config_path=yaml_path)
        reg.register("svc", description="服务", path="/tmp/svc.jsonl", persist=True)

        # 文件应已创建
        assert Path(yaml_path).exists()

        # 文件内容应包含该源
        with open(yaml_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert "svc" in raw.get("sources", {})

    def test_register_persist_readable_by_load_config(self, tmp_path):
        """5.4 register(persist=True) 后 load_config 能读到该源，关键字段一致。"""
        yaml_path = _minimal_yaml_path(tmp_path)
        reg = SourceRegistry(config_path=yaml_path)
        reg.register(
            "api",
            description="API 日志",
            path="/tmp/api.jsonl",
            fmt="jsonl",
            rotation="numeric",
            persist=True,
        )

        reloaded = load_config(yaml_path)
        assert "api" in reloaded
        assert reloaded["api"]["description"] == "API 日志"
        assert reloaded["api"]["path"] == "/tmp/api.jsonl"
        assert reloaded["api"]["rotation"] == "numeric"
        assert reloaded["api"]["format"] == "jsonl"
        # _persist_add 将空 field_map 写为 None；load_config/_validate_source
        # 内部用 `cfg.get("field_map") or {}` 处理，回读结果应为空 dict
        assert reloaded["api"]["field_map"] == {}

    def test_unregister_persist_removes_source_from_yaml(self, tmp_path):
        """5.5 unregister(persist=True) 后 load_config 不再包含该源。"""
        yaml_path = _minimal_yaml_path(tmp_path)
        reg = SourceRegistry(config_path=yaml_path)
        reg.register("api", description="API 日志", path="/tmp/api.jsonl", persist=True)
        reg.unregister("api", persist=True)

        reloaded = load_config(yaml_path)
        assert "api" not in reloaded

    def test_unregister_persist_source_only_in_memory_no_error(self, tmp_path):
        """5.6 源只在内存中、不在磁盘 yaml 里，unregister(persist=True) 不抛错，内存移除，yaml 保持无该源。"""
        yaml_path = _minimal_yaml_path(tmp_path)
        reg = SourceRegistry(config_path=yaml_path)
        # 仅注册到内存，不持久化
        reg.register("mem_only", description="纯内存源", path="/tmp/mem.jsonl", persist=False)

        # 确认磁盘 yaml 中无此源
        assert "mem_only" not in load_config(yaml_path)

        # unregister 加 persist=True，不应抛错（_persist_remove 容忍 yaml 中无该键）
        reg.unregister("mem_only", persist=True)

        # 内存已移除
        assert "mem_only" not in reg.list()
        # yaml 仍然无该源
        assert "mem_only" not in load_config(yaml_path)
