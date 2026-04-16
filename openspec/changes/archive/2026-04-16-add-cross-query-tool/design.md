# Design: 跨源关联查询

## SQL 构造策略

为每个参与关联的日志源构造独立的 CTE（Common Table Expression），每个 CTE 内部完成字段归一化和基础过滤，然后通过 INNER JOIN ON join_field 关联：

```sql
WITH source_a AS (
    SELECT *, 'source_a' AS _source, ...归一化字段
    FROM read_json_auto([files_a], ...)
    WHERE ...基础过滤
),
source_b AS (
    SELECT *, 'source_b' AS _source, ...归一化字段
    FROM read_json_auto([files_b], ...)
    WHERE ...基础过滤
)
SELECT a.*, b.*
FROM source_a a
JOIN source_b b ON a.join_field = b.join_field
ORDER BY a._timestamp
LIMIT $limit
```

## 参数化查询

与单源查询一致，所有过滤条件通过 $N 参数传入。join_field 作为列名使用双引号包裹，不作为参数值传入（列名不能参数化，但通过白名单校验确保安全）。

## 多源字段归一化

每个 CTE 内部独立应用各自源的 field_map 归一化。关联字段（join_field）要求在所有参与源中存在同名字段。

## 返回结构

合并条目按时间排序，每条附带 `_source` 字段标识来源：

```json
{
  "entries": [
    {
      "_source": "api-server",
      "_timestamp": "...",
      "correlation_id": "abc-123",
      ...其他字段
    }
  ]
}
```
