# Change: 为 server.py 的 MCP handler 层与启动流程添加测试

## Why
`server.py` 的 7 个 handler、`_file_status`、tool schema、`run_server` 初始化是 MCP 协议暴露面，目前零覆盖；Agent 的异常输入和 SDK 升级均无保底。

## What Changes
- 新增 `tests/test_server_handlers.py`，使用真实 `SourceRegistry` + engine + 临时 JSONL 日志源，覆盖 7 个 `_handle_*` 成功/源不存在/参数非法等分支
- 覆盖 `_file_status` 的文件存在、缺失、目录、无权限四种状态
- 对 `list_tools` 返回的 7 个 Tool 的 `inputSchema` 做 JSON Schema 合法性与必填字段断言
- 加入最小 smoke test：构造 server 对象或调用 `run_server` 初始化路径，断言 7 个 tool 均已注册
- 新增 `mcp-tool-handlers` spec 描述 handler 分发、错误包装、schema 暴露、启动注册的契约

## Impact
- Affected specs: new:mcp-tool-handlers
- Affected code: `log_mcp/server.py`（受测对象，不修改）；`tests/test_server_handlers.py`（新增）
- Dependencies: `add-config-loader-tests`（handler 层依赖 SourceRegistry 契约先稳固）
