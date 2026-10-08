# RabbitMQ 任务运行说明

## 当前范围

2026-10-08：提供 RabbitMQ 单机部署、MySQL outbox 投递器及 documents/agent 独立 Worker。默认两个执行模式仍为 `in_process`，启用前需按以下步骤启动长期进程并清理旧模式在途任务。本机已验证 Broker 停机接收/恢复投递、独立 CLI 消费及条件向量写入；本轮真实模型质量和完整业务浏览器矩阵未重测，具体范围见验收记录。

## 部署消息服务

需要 Docker Desktop 的 Linux 引擎。项目根目录的 `.env.rabbitmq` 仅保存本地部署配置，被 `.gitignore` 的 `.env.*` 规则排除；不要提交密码。首次部署前设置独立账号和随机密码：

```powershell
$taskBrokerPassword = [Convert]::ToHexString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
"RABBITMQ_USERNAME=chemicalops`nRABBITMQ_PASSWORD=$taskBrokerPassword" | Set-Content -Encoding utf8 .env.rabbitmq
docker compose --env-file .env.rabbitmq -f deploy/docker-compose.rabbitmq.yml config --quiet
docker compose --env-file .env.rabbitmq -f deploy/docker-compose.rabbitmq.yml up -d --wait
```

已有数据卷时不要覆盖账号密码文件；镜像初始化账号只在首次初始化数据目录时生效。凭据变化应通过 RabbitMQ 的账号管理操作处理。

管理地址为 `http://127.0.0.1:15672`，使用文件内的账号密码，vhost 为 `chemicalops`。AMQP 端口为 5672，开发环境两个端口仅绑定本机。

本机 Python 客户端使用 `127.0.0.1`；同一 Compose 网络中的容器使用服务名 `rabbitmq` 和容器内部端口 5672。其他 Compose 项目的容器不能直接使用此服务名，需显式接入相同网络。部署 Broker 不要求 API 或 Worker 一并容器化。

镜像固定为 `rabbitmq:4.3.6-management`；固定 hostname 和 nodename 配合 `rabbitmq_data` 卷保存消息。保留卷重建容器使用：

```powershell
docker compose --env-file .env.rabbitmq -f deploy/docker-compose.rabbitmq.yml up -d --force-recreate --wait
```

不要使用 `down -v` 作为普通停机步骤。数据卷不等于备份，单节点也不具备节点故障高可用。

## 配置与部署验收

当前后端 `.env` 保持：

```dotenv
TECHNICAL_DOCUMENT_EXECUTION_MODE=in_process
AGENT_EXECUTION_MODE=in_process
```

启用队列前配置 RabbitMQ 主机、端口、独立账号密码和 vhost。`.env.rabbitmq` 不自动被后端 Settings 加载；连接配置需配置于后端 `.env`。启用队列模式缺少凭据或使用 guest 会被拒绝，生产环境还拒绝占位密码。

专用持久消息验收不会操作业务队列：

```powershell
.venv/Scripts/python.exe scripts/verify_rabbitmq.py publish
docker compose --env-file .env.rabbitmq -f deploy/docker-compose.rabbitmq.yml up -d --force-recreate --wait
.venv/Scripts/python.exe scripts/verify_rabbitmq.py consume
```

验收成功后删除专用测试队列，保留 Broker 和数据卷。具体结果见 [验收记录](build-notes/RabbitMQ任务接入验收-20261008.md)。

## 启动独立任务进程

先运行现有数据库迁移工具升级至 041，并保留升级前备份。API、投递器和两个 Worker 必须连接同一个业务数据库。将 `.env.rabbitmq` 中实际账号密码配置到后端 `.env` 的 `RABBITMQ_USERNAME` / `RABBITMQ_PASSWORD`，并设置 `RABBITMQ_HOST=127.0.0.1`、`RABBITMQ_PORT=5672`、`RABBITMQ_VHOST=chemicalops`。

在三个独立终端启动：

```powershell
.venv/Scripts/python.exe scripts/run_task_dispatcher.py
.venv/Scripts/python.exe scripts/run_task_worker.py --queue documents
.venv/Scripts/python.exe scripts/run_task_worker.py --queue agent
```

每个进程可用 `--env-file <配置路径>` 指定环境；默认读取根目录 `.env`。投递器持续扫描 MySQL outbox，Broker 不可用时重连并保留投递意图；Worker 启动及空闲时扫描过期执行。进程应由服务管理器守护，终端关闭会停止本机 Worker，Docker 重启 Broker 不会自动启动 Python 进程。

仅投递一条或消费当前队列一条使用 `--once`。诊断与恢复入口：

```powershell
.venv/Scripts/python.exe scripts/run_task_dispatcher.py --status
.venv/Scripts/python.exe scripts/run_task_worker.py --queue documents --recover-only
```

`--status` 返回 outbox 按状态计数与最旧待投递延迟秒数；投递日志含 message_id/execution_id，执行日志含 execution_id/token/attempt。错误日志只记录受控代码或类型并过滤配置密钥。

```sql
SELECT id, task_type, business_id, status, attempt_count, delivery_generation,
       fencing_token, lease_owner, lease_until, next_attempt_at, error_code, checkpoint
FROM async_task_executions ORDER BY created_at DESC LIMIT 50;
SELECT execution_id, routing_key, status, available_at, attempt_count
FROM task_outbox WHERE status <> 'SENT' ORDER BY available_at LIMIT 50;
SELECT resource_key, execution_id FROM task_resource_locks;
```

执行暂时故障默认最多 3 次，等待约 30/120 秒；Broker 投递失败不计入执行次数。永久缺失资料、权限拒绝、版本不支持等直接失败；失败消息投递到 `chemicalops.documents.failed` / `chemicalops.agent.failed`，不自动执行。不要从管理界面直接重放隔离消息。

无法证明旧进程已停止时，任务以 `RECOVERY_ISOLATION_REQUIRED` 失败并保留资源锁。检查 checkpoint 中的 host/process_pid，确认真实任务进程及后代均已退出；不能仅按 PID 杀进程或直接删除资源锁。操作员完成隔离、核对资料状态后才能清理对应资源锁并从正常业务入口新建任务。旧 RUNNING 历史没有完整执行参数，不自动迁移。

## 分阶段启用与回滚

1. 暂停技术资料新提交，核对旧 BackgroundTasks 无在途任务；启动投递器和 documents Worker，设置 `TECHNICAL_DOCUMENT_EXECUTION_MODE=rabbitmq` 并重启 API。技术资料抽屉显示“等待执行 / 处理中 / 等待重试 / 完成 / 失败”，排队和重试仍对同 CAS 互斥。源 hash 有效时复用成功阶段，资料阶段仍有 900 秒上限。
2. 技术资料稳定后暂停 Agent 异步提交，结束或取消旧 RUNNING；保留 WAITING_INPUT，由用户合法续跑。启动 agent Worker，设置 `AGENT_EXECUTION_MODE=rabbitmq` 并重启 API。四个异步入口返回原 202/TaskRead，公开 RUNNING 包含队列等待，WAITING_INPUT 结束本次执行，人工续跑生成新代次。同步 create/continue 接口沿用原行为。取消终结关联执行，迟到回复不能覆盖取消结果。
3. 回滚先暂停新提交、停止投递器，等待在途执行完成或通过正常取消结束，并处理剩余 QUEUED/RETRYING；确认两个 Worker 及其子进程已停止后，设置两个模式为 `in_process` 并重启 API。保留执行/outbox/资源锁和 RabbitMQ 数据卷用于追溯。不要把旧队列执行记录交给 BackgroundTasks，也不要盲目重放历史 RUNNING。

向量阶段要求 Qdrant >=1.16、qdrant-client >=1.16。文档代次保存于 MySQL，条件 update_only 拒绝旧向量覆盖；insert_only 占位点不参与检索，目标文档旧点按 CAS/doc_type 清理。跨 MySQL/Qdrant 不提供原子事务，阶段完成仍需有效 token 和源 hash；换模型重建整个集合必须停机单独操作，队列执行禁止 `--recreate`。
