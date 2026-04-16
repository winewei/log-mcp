"""
日志源配置加载与注册管理。
支持从 sources.yaml 加载静态配置，也支持运行时动态注册/注销。
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 合法枚举值
VALID_ROTATIONS = {"numeric", "date", "none"}
VALID_FORMATS = {"jsonl", "text"}

# field_map 允许的键
VALID_FIELD_MAP_KEYS = {"timestamp", "level", "message"}


def _validate_source(name: str, cfg: dict) -> dict:
    """校验并补全单个日志源配置，返回标准化后的字典。"""
    if not isinstance(cfg.get("description"), str) or not cfg["description"]:
        raise ValueError(f"源 '{name}' 缺少必填字段 description")
    if not isinstance(cfg.get("path"), str) or not cfg["path"]:
        raise ValueError(f"源 '{name}' 缺少必填字段 path")

    rotation = cfg.get("rotation", "numeric")
    if rotation not in VALID_ROTATIONS:
        raise ValueError(f"源 '{name}' rotation 值无效: {rotation!r}，合法值: {VALID_ROTATIONS}")

    fmt = cfg.get("format", "jsonl")
    if fmt not in VALID_FORMATS:
        raise ValueError(f"源 '{name}' format 值无效: {fmt!r}，合法值: {VALID_FORMATS}")

    field_map = cfg.get("field_map") or {}
    invalid_keys = set(field_map.keys()) - VALID_FIELD_MAP_KEYS
    if invalid_keys:
        raise ValueError(f"源 '{name}' field_map 包含非法键: {invalid_keys}")

    return {
        "description": cfg["description"],
        "path": cfg["path"],
        "rotation": rotation,
        "format": fmt,
        "field_map": field_map,
    }


def load_config(config_path: str) -> dict[str, dict]:
    """从 YAML 文件加载所有日志源配置，返回 {name: validated_cfg} 字典。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    sources_raw = raw.get("sources") or {}
    if not isinstance(sources_raw, dict):
        raise ValueError("sources.yaml 中 'sources' 字段必须是对象（mapping）")

    sources: dict[str, dict] = {}
    for name, cfg in sources_raw.items():
        sources[name] = _validate_source(name, cfg or {})

    logger.info("从配置文件加载了 %d 个日志源: %s", len(sources), config_path)
    return sources


class SourceRegistry:
    """
    日志源注册表，持有全部日志源（静态配置 + 动态注册）。
    config_path 用于 persist 操作时回写 YAML。
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._sources: dict[str, dict] = {}
        self._config_path: str | None = config_path

    def load_from_file(self, config_path: str) -> None:
        """从配置文件加载并合并到注册表（覆盖同名项）。"""
        self._config_path = config_path
        sources = load_config(config_path)
        self._sources.update(sources)

    def register(
        self,
        name: str,
        description: str,
        path: str,
        fmt: str = "jsonl",
        rotation: str = "numeric",
        field_map: dict | None = None,
        persist: bool = False,
    ) -> None:
        """注册一个新日志源；persist=True 时同步写入 sources.yaml。"""
        cfg_raw: dict[str, Any] = {
            "description": description,
            "path": path,
            "format": fmt,
            "rotation": rotation,
        }
        if field_map:
            cfg_raw["field_map"] = field_map

        validated = _validate_source(name, cfg_raw)
        self._sources[name] = validated
        logger.info("注册日志源: %s -> %s", name, path)

        if persist:
            self._persist_add(name, validated)

    def unregister(self, name: str, persist: bool = False) -> None:
        """注销日志源；persist=True 时同步从 sources.yaml 中删除。"""
        if name not in self._sources:
            raise KeyError(f"日志源不存在: {name}")
        del self._sources[name]
        logger.info("注销日志源: %s", name)

        if persist:
            self._persist_remove(name)

    def get(self, name: str) -> dict:
        """获取单个日志源配置，不存在时抛 KeyError。"""
        if name not in self._sources:
            raise KeyError(f"日志源不存在: {name}")
        return self._sources[name]

    def list(self) -> dict[str, dict]:
        """返回全部日志源配置的浅拷贝。"""
        return dict(self._sources)

    def _load_yaml_raw(self) -> dict:
        """读取当前 sources.yaml 原始内容（用于 persist 操作）。"""
        if not self._config_path:
            raise RuntimeError("未指定 config_path，无法执行 persist 操作")
        p = Path(self._config_path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _write_yaml_raw(self, raw: dict) -> None:
        """将原始字典回写到 sources.yaml。"""
        p = Path(self._config_path)  # type: ignore[arg-type]
        with p.open("w", encoding="utf-8") as f:
            yaml.dump(raw, f, allow_unicode=True, sort_keys=False)

    def _persist_add(self, name: str, cfg: dict) -> None:
        """将新日志源追加写入 sources.yaml。"""
        raw = self._load_yaml_raw()
        raw.setdefault("sources", {})[name] = {
            "description": cfg["description"],
            "path": cfg["path"],
            "rotation": cfg["rotation"],
            "format": cfg["format"],
            "field_map": cfg["field_map"] or None,
        }
        self._write_yaml_raw(raw)
        logger.info("已将日志源 '%s' 持久化写入 %s", name, self._config_path)

    def _persist_remove(self, name: str) -> None:
        """从 sources.yaml 中删除指定日志源。"""
        raw = self._load_yaml_raw()
        sources = raw.get("sources") or {}
        if name in sources:
            del sources[name]
            raw["sources"] = sources
            self._write_yaml_raw(raw)
            logger.info("已将日志源 '%s' 从 %s 中删除", name, self._config_path)
