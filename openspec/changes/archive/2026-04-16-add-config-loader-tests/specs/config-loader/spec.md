# Spec: Config Loader

## ADDED Requirements

### Requirement: Source Config Validation

配置加载器 MUST 对每个日志源配置执行必填字段、枚举值、字段映射键的校验，并补全默认值。

#### Scenario: 缺少 description 抛错

- **WHEN** 传入的源配置 `description` 为空字符串或缺失
- **THEN** `_validate_source` 抛出 `ValueError` 并在消息中注明缺失字段

#### Scenario: 缺少 path 抛错

- **WHEN** 传入的源配置 `path` 为空或缺失
- **THEN** `_validate_source` 抛出 `ValueError`

#### Scenario: 非法 rotation 值

- **WHEN** 源配置 `rotation` 不属于 `numeric`/`date`/`none`
- **THEN** `_validate_source` 抛出 `ValueError`

#### Scenario: 非法 format 值

- **WHEN** 源配置 `format` 不属于 `jsonl`/`text`
- **THEN** `_validate_source` 抛出 `ValueError`

#### Scenario: field_map 含非法键

- **WHEN** 源配置 `field_map` 包含 `timestamp`/`level`/`message` 以外的键
- **THEN** `_validate_source` 抛出 `ValueError`

#### Scenario: field_map 缺省补全

- **WHEN** 源配置未提供 `field_map`
- **THEN** 返回的标准化配置中 `field_map` 为空 dict，且 `rotation` 默认 `numeric`、`format` 默认 `jsonl`

### Requirement: Config File Loading

配置加载器 MUST 以只读方式从给定的 YAML 文件解析日志源列表，并在路径或内容异常时抛出明确错误。

#### Scenario: 文件不存在

- **WHEN** 调用 `load_config(path)` 但路径不存在
- **THEN** 抛出 `FileNotFoundError`

#### Scenario: YAML 语法错误

- **WHEN** 目标 YAML 内容非法（无法解析）
- **THEN** 抛出 `yaml.YAMLError`

#### Scenario: sources 字段类型错误

- **WHEN** YAML 顶层 `sources` 字段存在但不是对象（mapping）
- **THEN** 抛出 `ValueError`

#### Scenario: 缺少 sources 键

- **WHEN** YAML 文件为空或缺少 `sources` 键
- **THEN** 返回空 dict，不抛错

#### Scenario: 多源正常加载

- **WHEN** YAML 中定义了多个合法日志源
- **THEN** 返回的 dict 的 key 为源名，value 为经 `_validate_source` 标准化后的配置

#### Scenario: 单源校验失败冒泡

- **WHEN** YAML 中某个源因字段非法导致 `_validate_source` 报错
- **THEN** `load_config` 将同一 `ValueError` 向上抛出

### Requirement: In-Memory Source Registry

`SourceRegistry` MUST 在内存中提供对日志源的注册、注销、读取与枚举能力，并在不存在时以 `KeyError` 表达缺失。

#### Scenario: load_from_file 合并

- **WHEN** 在已有内存源的 Registry 上调用 `load_from_file` 加载一个新的 YAML
- **THEN** YAML 中的源合并到内存中；若同名，以 YAML 中的配置覆盖旧值

#### Scenario: register 写入与可见

- **WHEN** 调用 `register` 注册一个新源
- **THEN** 随后 `get(name)` 返回标准化配置，`list()` 包含该源

#### Scenario: register 同名覆盖

- **WHEN** 对已有源名再次调用 `register`
- **THEN** 内存中的该源被新配置覆盖，不抛错

#### Scenario: unregister 移除成功

- **WHEN** 对已存在的源名调用 `unregister`
- **THEN** 该源从内存移除，`get(name)` 抛 `KeyError`

#### Scenario: unregister 不存在抛错

- **WHEN** 对不存在的源名调用 `unregister`
- **THEN** 抛出 `KeyError`

#### Scenario: get 不存在抛错

- **WHEN** 对不存在的源名调用 `get`
- **THEN** 抛出 `KeyError`

#### Scenario: list 返回浅拷贝

- **WHEN** 调用 `list()` 后修改返回的 dict
- **THEN** 注册表内部状态不受影响

### Requirement: Persistent Source Registry

`SourceRegistry` MUST 在 `persist=True` 时将注册/注销同步到 `config_path` 指向的 YAML 文件，且在未设置路径时拒绝该操作。

#### Scenario: 未设置 config_path 时 register persist 抛错

- **WHEN** 构造 Registry 未指定 `config_path`，却调用 `register(..., persist=True)`
- **THEN** 抛出 `RuntimeError`

#### Scenario: 未设置 config_path 时 unregister persist 抛错

- **WHEN** 构造 Registry 未指定 `config_path`，却调用 `unregister(..., persist=True)`
- **THEN** 抛出 `RuntimeError`

#### Scenario: 目标 YAML 不存在时按空字典初始化

- **WHEN** `config_path` 指向尚不存在的 YAML 文件，调用 `register(..., persist=True)`
- **THEN** 创建新 YAML 文件，`sources` 字段包含新注册的源

#### Scenario: register persist 写入可回读

- **WHEN** 调用 `register(..., persist=True)` 后再调用 `load_config(config_path)`
- **THEN** 返回的 dict 中包含刚注册的源，且字段与内存一致

#### Scenario: unregister persist 删除可回读

- **WHEN** 对已持久化的源调用 `unregister(..., persist=True)` 后再调用 `load_config(config_path)`
- **THEN** 返回的 dict 中不再包含该源

#### Scenario: unregister persist 目标不在 YAML 中

- **WHEN** 源存在于内存但不在磁盘 YAML 中，调用 `unregister(..., persist=True)`
- **THEN** YAML 文件保持不变，内存中该源被移除，不抛错
