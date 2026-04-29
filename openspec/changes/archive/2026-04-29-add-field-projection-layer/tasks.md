# Tasks

## 1. 公共裁剪层
- [x] 1.1 在 log_mcp/engine.py 新增 _project_fields(rows, fields, truncate_threshold=4096) 函数
- [x] 1.2 实现单字段值序列化后超过 4KB 时替换为 `<truncated:<size>>` 占位符（含可读单位 KB/MB）
- [x] 1.3 实现归一化字段保留逻辑：fields 未传时强制保留 _timestamp/_level/_message/_source
- [x] 1.4 实现白名单分支：fields 传入时仅返回该列表字段，未存在字段补 NULL，不参与截断

## 2. 接入查询路径
- [x] 2.1 query_entries 在结果序列化前调用 _project_fields，透传 fields 参数
- [x] 2.2 tail_entries 在结果序列化前调用 _project_fields，透传 fields 参数

## 3. inputSchema 更新
- [x] 3.1 server.py 中 query/tail 两个 Tool inputSchema 增加 fields 参数（list[str]，可选）
- [x] 3.2 _handle_query / _handle_tail 透传 fields 至 engine 层

## 4. 测试
- [x] 4.1 默认裁剪：单字段 100KB 被替换为 `<truncated:100.0KB>`
- [x] 4.2 白名单：传 fields=["_timestamp","_message"] 仅返回两字段
- [x] 4.3 白名单内大字段不被截断，原值返回
- [x] 4.4 fields 含不存在字段时返回 NULL 不报错
- [x] 4.5 _timestamp 字段无论多大都保留原值
