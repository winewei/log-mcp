## 1. 描述改写
- [x] 1.1 list_sources description 改为"首次进入项目时调用：发现可查询的日志源、确认文件状态"
- [x] 1.2 query description 改为"已知过滤条件时使用：按级别 / 字段 / 时间窗口精确检索，支持分页"
- [x] 1.3 tail description 改为"快速看最新动态：诊断刚发生的问题，比 query 省参数"
- [x] 1.4 summary description 改为"判断服务健康状况：错误率、分位数、趋势；代码变更后第一次检查首选"
- [x] 1.5 cross_query description 改为"重建跨源调用时间线：用 correlation_id 等共享字段串起多服务事件"
- [x] 1.6 register_source description 改为"临时排障引入新源：可选 persist 持久化"
- [x] 1.7 unregister_source description 改为"清理不再需要的源：可选 persist 同步删除"

## 2. 测试
- [x] 2.1 测试 list_tools 返回的 7 个 description 字段内容与上述一致
- [x] 2.2 每条 description 单句长度 ≤50 字
