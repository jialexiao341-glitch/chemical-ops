# 后端观测与运行验收

- 宿主机 API `http://127.0.0.1:8888/health/ready` 返回 200；MySQL、迁移和 MinIO 检查均为 `ok`。`/metrics` 返回 200，包含 API 请求、数据库 SQL 计数、连接池状态、MySQL 持久队列快照及任务执行耗时 gauge。
- Redis 7 在 `127.0.0.1:6380` healthy；Redis 缓存命中率和数据库查询次数对照见 [接口压测证据](api-load-test-2026-10-14.json)。
- Docker Hub 镜像代理 `docker.m.daocloud.io` 返回 HTTP 502，Docker Hub 直连获取匿名令牌也因 EOF 失败。改用 `mirror.gcr.io` 后已成功拉取并启动 Prometheus `v3.5.0`、Grafana `12.1.1` 和 Jaeger `1.76.0`；Compose 配置已固定为该镜像路径。三个容器均为 `Up`，Prometheus `/-/ready` 返回 200，Grafana `/api/health` 为 `ok`，Jaeger 容器已运行。
- Prometheus 已发现 `chemicalops-api` target 且 health 为 `up`，查询 `up{job="chemicalops-api"}` 得到 1；API 请求速率、API P95、队列积压和数据库连接池等查询已有样本。Grafana 已加载 `ChemicalOps 后端运行概览`，面板包含队列积压、API P95、LLM Gateway P95 和 LLM 首 Token P95。验收时 LLM Gateway、TTFT、Agent 工具调用近 5 分钟没有样本，所以对应延迟/成功率面板当前会显示无数据，需产生模型请求后再确认实际曲线。
- OpenTelemetry 配置、依赖和 API/Worker/Agent/LLM instrumentation 已接入；本地 OTLP collector 替身收到同一 trace ID 下的 API、Agent、Worker、HTTPX/LLM 和 SQLAlchemy spans。Jaeger UI 容器现已启动，但当前 `.env` 保持 `OTEL_ENABLED=false`，需启用并发送请求后才能在 UI 看到真实链路。
- API 指标是进程内累计值，多实例时必须逐实例抓取；Gateway 熔断器和并发 semaphore 也是进程内状态，当前策略保持单 API 实例。任务调度按资料/Agent 队列分别 FIFO，不做跨队列优先级或公平调度。
- 迁移 050 已通过迁移脚本执行自动备份后应用；数据库备份见 `backups/mysql/chemicalops_20261014_113103.sql`。任务耗时看板值是最近 15 分钟已完成尝试均值；当前窗口无已完成样本时为 0，不能解释为耗时为零。
- 跨主机旧 Worker 无法确认退出时的人工隔离、证据保留和恢复步骤见 [数据库任务队列运行说明](../数据库任务队列运行说明.md)。
