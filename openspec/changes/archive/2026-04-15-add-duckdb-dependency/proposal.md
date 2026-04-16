# Change: 新增 DuckDB 依赖声明

## Why
DuckDB 是整个查询引擎重构的基础运行时依赖，所有后续 change 都依赖此包可用。

## What Changes
- pyproject.toml dependencies 新增 duckdb>=1.2

## Impact
- Affected specs: modify:project-dependencies
- Affected code: pyproject.toml
