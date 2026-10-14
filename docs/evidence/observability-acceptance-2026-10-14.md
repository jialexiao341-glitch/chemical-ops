# 后端观测与运行验收

- 宿主机 API `http://127.0.0.1:8888/health/ready` 返回 200；MySQL、迁移和 MinIO 检查均为 `ok`。`/metrics` 返回 200，包含 API 请求、数据库 SQL 计数、连接池状态、MySQL 持久队列快照及任务执行耗时 gauge。
- Redis 7 在 `127.0.0.1:6380` healthy；Redis 缓存命中率和数据库查询次数对照见 [接口压测证据](api-load-test-2026-10-14.json)。
- Docker Hub 镜像代理 `docker.m.daocloud.io` 返回 HTTP 502，Docker Hub 直连获取匿名令牌也因 EOF 失败。改用 `mirror.gcr.io` 后已成功拉取并启动 Prometheus `v3.5.0`、Grafana `12.1.1` 和 Jaeger `1.76.0`；Compose 配置已固定为该镜像路径。三个容器均为 `Up`，Prometheus `/-/ready` 返回 200，Grafana `/api/health` 为 `ok`，Jaeger 容器已运行。
- Prometheus 已发现 `chemicalops-api` target 且 health 为 `up`，查询 `up{job="chemicalops-api"}` 得到 1；API 请求速率、API P95、队列积压和数据库连接池等查询已有样本。Grafana 已加载 `ChemicalOps 后端运行概览`，面板包含队列积压、API P95、LLM Gateway P95 和 LLM 首 Token P95。验收时 LLM Gateway、TTFT、Agent 工具调用近 5 分钟没有样本，所以对应延迟/成功率面板当前会显示无数据，需产生模型请求后再确认实际曲线。
- OpenTelemetry 配置、依赖和 API/Worker/Agent/LLM instrumentation 已接入；本地 OTLP collector 替身收到同一 trace ID 下的 API、Agent、Worker、HTTPX/LLM 和 SQLAlchemy spans。Jaeger UI 容器现已启动，但当前 `.env` 保持 `OTEL_ENABLED=false`，需启用并发送请求后才能在 UI 看到真实链路。
- API 指标是进程内累计值，多实例时必须逐实例抓取；Gateway 熔断器和并发 semaphore 也是进程内状态，当前策略保持单 API 实例。任务调度按资料/Agent 队列分别 FIFO，不做跨队列优先级或公平调度。
- 迁移 050 已通过迁移脚本执行自动备份后应用；数据库备份见 `backups/mysql/chemicalops_20261014_113103.sql`。任务耗时看板值是最近 15 分钟已完成尝试均值；当前窗口无已完成样本时为 0，不能解释为耗时为零。
- 跨主机旧 Worker 无法确认退出时的人工隔离、证据保留和恢复步骤见 [数据库任务队列运行说明](../数据库任务队列运行说明.md)。

## 工程化收尾复核

- Prometheus 主配置和新增 6 条规则通过 `promtool check config` / `promtool check rules`；Prometheus API 显示规则已加载，`chemicalops-api` target 为 `up`。Grafana 重建后 `/api/health` 正常，搜索确认已加载 `ChemicalOps 后端运行概览`，看板共 13 个面板。
- 新增任务隔离状态指标 `chemicalops_task_queue_isolation_required`。Grafana/告警对 MySQL 共享队列快照按 queue 取 max 去重；Counter/Histogram 仍按实例保留后聚合，数据库连接池面板保留 instance。多实例目标仍需逐个加入 Prometheus 配置。
- 真实 MySQL + Redis 产品详情冷/热各 100 请求均成功，缓存 miss/hit 均为 100，数据库 SELECT 304/204；P50/P95/P99、QPS 和事件覆盖率见[冷/热报告](product-detail-cache-cold-hot-2026-10-14.json)。结果是本机单并发短样本。
- 产品详情 API 并发 10、200 请求的一次样本为 200/200 成功；独立复跑 198/200 成功，另有 2 次连接中断，两个样本 P99 都约 7 秒。报告分别保存在 [成功样本](api-load-test-2026-10-14.json) 和 [复跑样本](api-load-test-repeat-2026-10-14.json)，不能据此宣称稳定容量或延迟改善。
- 后续续验已接入 Alertmanager 与用户指定的本地专用 webhook，完成真实 Prometheus 触发、恢复、重复抑制和接收器落盘确认；完成管理员/普通用户监控页浏览器及真实 HTTP 权限验收。用户确认并发 2、8 请求、8,000 Token 上限后，真实模型样本 8/8 成功、实际 732 Token。详见[ENG-05 续验记录](eng05-completion-2026-10-14.md)。这是本地通知与受控小样本并发结果，不代表生产外部通知或容量评估；前端全量类型检查仍有既有 Vue 类型依赖错误。
