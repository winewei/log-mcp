## 1. server.py schema 变更
- [x] 1.1 summary tool inputSchema 新增 percentile_fields 参数（type: array, items: string，可选）
- [x] 1.2 summary tool inputSchema 新增 bucket_interval 参数（type: string，可选，enum: ["1m", "5m", "1h"]）

## 2. engine.py 实现
- [x] 2.1 summarize_entries() 签名新增 percentile_fields 和 bucket_interval 参数
- [x] 2.2 percentile_fields 非空时，生成 approx_quantile SQL 查询 p50/p95/p99
- [x] 2.3 bucket_interval 非空时，生成 time_bucket 聚合 SQL（按桶统计 total 和 errors）
- [x] 2.4 bucket_interval 字符串映射：1m → INTERVAL '1 minute'，5m → INTERVAL '5 minutes'，1h → INTERVAL '1 hour'

## 3. 返回结构
- [x] 3.1 percentiles 字段：dict[str, dict[str, float]]，未传时省略
- [x] 3.2 time_buckets 字段：list[dict]，每项含 bucket/total/errors，未传时省略
