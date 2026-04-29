# Change: Tool description 重写为 when-to-use 引导

## Why
现有 description 仅描述功能，Agent 选用工具缺乏语义引导；改为"何时用 + 做什么"帮助 Agent 在健康检查、链路重建等场景下精准选型。

## What Changes
- 重写 7 个 tool 的 description，单句 ≤50 字
- 格式统一为 "when to use" 在前、"做什么" 在后
- 保持中文风格，不引入 examples 字段

## Impact
- Affected specs: modify:mcp-tool-handlers
- Affected code: log_mcp/server.py（_TOOLS 列表中 7 个 Tool 的 description 字段）
