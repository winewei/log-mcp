# Design: DuckDB 查询引擎

## 选型理由

DuckDB 作为嵌入式分析数据库，原生支持 JSONL 文件直读（`read_json_auto`）、SQL 过滤/聚合/JOIN。相比自研的 Python 循环解析 + 手写过滤，DuckDB 向量化执行在 10-100MB 日志文件上快 10-20 倍，且天然支持跨源 JOIN——这是当前架构完全不具备的能力。

## 双模式文件读取

- **JSONL 模式**：`read_json_auto(files, format='newline_delimited', ignore_errors=true, filename=true)`，自动推断 schema，跳过解析失败行，附带来源文件名
- **Text 模式**：`read_csv(files, header=false, columns={'column0': 'VARCHAR'})`，单列读取纯文本日志，仅支持 message_pattern 正则过滤

## 过滤器到参数化 SQL 的映射

当前 `field_filters` 支持 5 种语法，全部映射为参数化 SQL：

| MCP 语法 | SQL 等价 | 参数化方式 |
|---------|---------|-----------|
| `"value"` 精确匹配 | `col = $N` | 值作为参数 |
| `"~pattern"` 正则 | `regexp_matches(col, $N)` | 模式作为参数 |
| `">=N"` 数值比较 | `CAST(col AS DOUBLE) >= $N` | 数值作为参数 |
| `"!value"` 取反 | `col != $N OR col IS NULL` | 值作为参数 |

**安全性**：所有用户输入通过 DuckDB 参数化查询（`$1`, `$2`, ...）传入，不拼接进 SQL 字符串，杜绝 SQL 注入。

## 连接管理

采用 `:memory:` 模式，DuckDB 仅作为查询引擎，不持久化数据：

- **默认策略**：每次工具调用创建临时连接，执行完毕关闭。无状态，无需管理连接池或事务
- **优化策略**：对高频调用场景（如 tail），可复用模块级全局连接避免重复初始化开销

## 字段归一化

通过 `field_map` 配置将各日志源的字段名映射为统一的内部字段：
- `_timestamp` ← field_map.timestamp（默认 "timestamp"）
- `_level` ← field_map.level（默认 "level"）
- `_message` ← field_map.message（默认 "message"）

归一化在 SQL SELECT 层完成，不修改原始数据。
