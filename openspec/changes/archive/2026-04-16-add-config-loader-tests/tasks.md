# Implementation Tasks

## 1. 测试脚手架
- [x] 1.1 在 `tests/test_config.py` 中新增 helper，使用 pytest `tmp_path` 生成临时 YAML 源配置文件
- [x] 1.2 提供用于 SourceRegistry 持久化场景的最小有效 YAML fixture

## 2. `_validate_source` 单元测试
- [x] 2.1 缺少 `description` 抛 `ValueError`
- [x] 2.2 缺少或空 `path` 抛 `ValueError`
- [x] 2.3 非法 `rotation` 抛 `ValueError`
- [x] 2.4 非法 `format` 抛 `ValueError`
- [x] 2.5 `field_map` 缺省时返回空 dict，不报错
- [x] 2.6 `field_map` 含非法键抛 `ValueError`
- [x] 2.7 正常输入返回包含全部标准化字段的 dict

## 3. `load_config` 单元测试
- [x] 3.1 路径不存在时抛 `FileNotFoundError`
- [x] 3.2 YAML 语法错误抛 `yaml.YAMLError`
- [x] 3.3 顶层 `sources` 非对象（如列表）抛 `ValueError`
- [x] 3.4 空文件或缺 `sources` 键返回空 dict
- [x] 3.5 多源正常加载返回全部标准化配置
- [x] 3.6 单源校验失败时冒泡 `ValueError`

## 4. `SourceRegistry` 纯内存行为测试
- [x] 4.1 `load_from_file` 将 YAML 内容合并到空注册表
- [x] 4.2 `load_from_file` 与已有内存源重名时覆盖
- [x] 4.3 `register` 写入内存后 `get`/`list` 可见
- [x] 4.4 `register` 同名再次调用直接覆盖
- [x] 4.5 `unregister` 对已存在源移除成功
- [x] 4.6 `unregister` 对不存在源抛 `KeyError`
- [x] 4.7 `get` 对不存在源抛 `KeyError`
- [x] 4.8 `list` 返回浅拷贝（改动返回值不影响内部状态）

## 5. `SourceRegistry` 持久化路径
- [x] 5.1 `register(persist=True)` 未设置 `config_path` 时抛 `RuntimeError`
- [x] 5.2 `unregister(persist=True)` 未设置 `config_path` 时抛 `RuntimeError`
- [x] 5.3 `register(persist=True)` 目标 YAML 不存在时按空字典初始化并写入
- [x] 5.4 `register(persist=True)` 写入后 `load_config` 可读回同一源
- [x] 5.5 `unregister(persist=True)` 后再读 YAML，该源已不存在
- [x] 5.6 `unregister(persist=True)` 目标源不在 YAML 中时不报错

## 6. 验证
- [x] 6.1 运行 `pytest tests/test_config.py` 全部通过
- [x] 6.2 运行 `pytest` 全量回归无退化
