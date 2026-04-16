<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# LOG MCP Server

## 项目定位

通用日志查询 MCP Server，供 AI Agent（Claude Code）在开发/测试过程中查询任意服务的结构化日志。

**核心价值**：将 Agent 对日志的访问从 `grep`/`awk` 拼管道升级为参数化 SQL 查询，覆盖以下典型场景：
- 代码变更后快速定位错误（按级别/时间窗口过滤）
- 单次调用链排障（按 `correlation_id`/`trace_id` 过滤）
- 服务健康状况聚合（分位数/时间桶/分组统计）
- 跨服务/跨端链路重建（通过共享字段 INNER JOIN 多个日志源）

## 技术栈

- Python 3.11+
- MCP SDK：`mcp` (PyPI)
- 配置：PyYAML
- Transport：stdio（Claude Code 直连）
- 无外部数据库依赖，直接读取日志文件

## 实现要求

- 完整方案见 `DESIGN.md`，按该文档实现
- 所有代码直接最终版本，不分阶段
- 不要过度设计，保持精简
- 中文注释

## 快速开始

实现完成后，使用方式：

```bash
# 带配置文件启动
python -m log_mcp --config /path/to/sources.yaml

# 无配置启动（纯动态注册）
python -m log_mcp
```

Claude Code 项目配置（`.claude/settings.local.json`）：

```json
{
  "mcpServers": {
    "log": {
      "command": "python",
      "args": ["-m", "log_mcp", "--config", "/path/to/sources.yaml"]
    }
  }
}
```
