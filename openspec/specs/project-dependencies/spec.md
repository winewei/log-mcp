# project-dependencies Specification

## Purpose
TBD - created by archiving change add-duckdb-dependency. Update Purpose after archive.
## Requirements
### Requirement: Runtime Dependencies

项目 MUST 在 pyproject.toml 的 dependencies 中声明所有运行时依赖，包含版本下界约束。

#### Scenario: duckdb 依赖已声明

- **WHEN** 读取 pyproject.toml 的 dependencies 列表
- **THEN** 列表中包含 duckdb>=1.2

