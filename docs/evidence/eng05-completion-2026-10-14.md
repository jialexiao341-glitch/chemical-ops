# ENG-05 续验结果

范围：本机 Windows、单 API、真实开发 MySQL/RBAC、真实 Prometheus v3.5.0 与 Alertmanager v0.28.1、专用本地 webhook；真实模型 Gateway 固定短提示。用户确认并发 2、8 请求、最多 8,000 Token，以及本地通知目标。没有修改账号密码、业务队列记录或生产通知目标。

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| 真实监控 HTTP 权限 | 管理员 200，采购员/仓库账号均 403，匿名 401；管理员响应为真实 Prometheus 裁剪汇总 | [HTTP 证据](monitoring-permissions-2026-10-14.json) |
| 管理员浏览器 | 菜单可见，告警/目标/6 条规则可读；修复四个普通文本列缺少字段绑定，刷新后内容正常 | [管理员截图](monitoring-admin-2026-10-14.png) |
| 普通用户浏览器 | buyer 无系统管理/监控菜单，直接输入监控 URL 显示 404 | [菜单截图](monitoring-buyer-menu-2026-10-14.png)、[拒绝访问截图](monitoring-buyer-denied-2026-10-14.png) |
| 权限回归 | `tests/test_monitoring_api.py` 6 passed；真实登录与 MySQL 事务回滚，自动化测试中的 Prometheus 响应为替身 | 与上方运行中真实 HTTP 验收分开计数 |
| 真实模型并发 | deepseek-flash，8/8 返回非空结果，usage 全部可用，总计 732 Token；总耗时 5.791 秒，P50/P95/P99 为 1133.43/1774.31/1774.31 ms | [完整逐请求报告](real-model-load-2026-10-14.json) |
| 通知触发与恢复 | 临时规则由 Prometheus 计算，接收器收到 firing 和 resolved，同一 fingerprint；结束时删除临时规则，正式 6 条规则保留 | [通知原始载荷](alert-notifications-2026-10-14.json) |
| 重复抑制和送达确认 | 同一告警重复提交 3 次均 HTTP 200，观察 25 秒仅一条 firing 通知；接收器先落盘再应答 | 同上；25 秒超过两个 group_interval，未覆盖 4 小时重复提醒或 HA 去重 |

配置校验：`amtool check-config`、`promtool check config`、`promtool check rules` 均通过。通知接收记录保存在专用 Docker volume；未停止 API，也未清理仍存在的业务失败任务告警。

最终相关回归：`tests/test_monitoring_api.py tests/test_observability.py` 合计 **8 passed**，有一条既有 Starlette/AnyIO 弃用提示。额外验证 Token 预算不足时脚本拒绝执行且不生成报告；新增脚本语法检查及 `git diff --check` 通过。

前端使用现有页面组件、布局与样式，仅修复字段绑定。浏览器功能验收通过；全量 `vue-tsc --noEmit --skipLibCheck` 仍失败，包含全项目既有 `Module 'vue' has no exported member 'ref'/'computed'` 等依赖类型错误，日志在本地 `tmp/eng05-typecheck.log`。因此不宣称前端全量类型检查或生产构建通过。

结论：用户指定的 ENG-05 本地验收范围已完成。真实模型为受控小样本，不能视作生产容量/业务质量评估；本地 webhook 送达不能替代生产邮件、IM 或外部 webhook 送达验收。此前业务 API 复跑中的 2 次连接中断与约 7 秒 P99 长尾仍按原始报告保留。
