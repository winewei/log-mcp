# Change: 公共字段裁剪与白名单层

## Why
默认全字段返回易使大 body/headers 撑爆 Agent 上下文；引入 4KB 默认截断与 fields 白名单跨 tool 共享。

## What Changes
- 新增公共裁剪函数：单字段值 >4KB 替换为 <truncated:size> 占位符
- fields 未传时按默认裁剪策略：强制保留 _timestamp/_level/_message/_source 四个归一化字段，并对其余字段执行大字段截断
- fields 传入时按白名单返回：仅返回 fields 列出的字段（归一化字段如需保留必须显式列入），白名单字段不参与大字段截断（原值返回）
- fields 含不存在字段时该字段返回 NULL 不报错
- mcp-tool-handlers 在 query/tail/cross_query 三个工具的 inputSchema 中新增可选参数 fields: list[str]

## Impact
- Affected specs: modify:query-tool, modify:tail-tool, modify:mcp-tool-handlers
- Affected code: log_mcp/engine.py（裁剪函数、query_entries、tail_entries 输出路径）, log_mcp/server.py（query/tail 两个 tool 的 inputSchema 与 handler 透传）
