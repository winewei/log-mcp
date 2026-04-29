# Change: 统一结构化错误响应 Schema

## Why
当前裸 KeyError/Exception 消息让 Agent 无法自我恢复；引入 error_code/detail/suggestion/hints 四段式让错误可执行。

## What Changes
- 定义错误 schema：error_code、detail、suggestion、hints
- 覆盖 source_not_found / field_not_found / time_parse_error / join_field_not_allowed / internal_error 五类
- 重构 server.py 顶层异常处理统一走新 schema，移除旧 {error: ...} 字段

## Impact
- Affected specs: modify:mcp-tool-handlers
- Affected code: log_mcp/server.py（call_tool 异常路径）, log_mcp/engine.py（_parse_time 等可能抛错路径）
