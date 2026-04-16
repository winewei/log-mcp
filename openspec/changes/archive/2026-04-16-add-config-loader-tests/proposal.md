# Change: 为 config.py 添加配置加载与源注册表测试

## Why
`log_mcp/config.py` 承担 YAML 加载、字段校验、SourceRegistry 增删与持久化，目前零覆盖；任何回归都会导致所有查询失效，必须建立契约保护。

## What Changes
- 新增 `tests/test_config.py`，覆盖 `_validate_source` 的必填/非法值/field_map 默认合并分支
- 覆盖 `load_config` 的文件不存在、YAML 语法错误、缺 `sources` 键、同名源冲突、正常多源加载
- 覆盖 `SourceRegistry` 的 `load_from_file`/`register`/`unregister`/`get`/`list` 正常路径，以及 `register(persist=True)` 与 `unregister(persist=True)` 触发的 YAML 持久化行为；验证重名覆盖、注销不存在源抛 `KeyError`、未设置 `config_path` 时 persist 抛 `RuntimeError`、目标 YAML 不存在时按空字典初始化等边界
- 新增 `config-loader` spec 描述配置加载器可验证行为契约

## Impact
- Affected specs: new:config-loader
- Affected code: `log_mcp/config.py`（受测对象，不修改）；`tests/test_config.py`（新增）
