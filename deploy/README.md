# ChemicalOps 容器配置

项目使用的容器配置集中在本目录，`compose.yaml` 是统一入口，Compose 项目名为 `chemicalops`。单服务文件通过 `extends` 复用统一定义，不再单独维护一套配置。

| 服务 | 默认宿主地址 | 数据保存方式 |
| --- | --- | --- |
| MinIO API | `127.0.0.1:19000` | 命名卷 `chemicalops_minio_data` |
| MinIO 控制台 | `127.0.0.1:19001` | 与 API 共用数据 |
| Qdrant | `127.0.0.1:6333` | 命名卷 `chemicalops_qdrant_data` |
| Redis | `127.0.0.1:6380` | 可重建缓存，不启用 RDB/AOF |
| minio-init | 无宿主端口 | 创建三个配置的私有桶，完成后退出 |

表中的卷名是 Compose 逻辑名，实际名称由 `chemicalops` 项目名前缀生成。这里不接管其他项目的卷。

MySQL 继续由项目 `.env` 中的连接配置指向现有本机实例。异步任务使用 MySQL 持久队列，RabbitMQ 已退役，故不纳入本配置。其他项目的 Elasticsearch、Neo4j 等容器也不在管理范围内。

## 本次整理与现有实例

本次只整理文件并校验配置，没有启动、停止、重建或迁移容器，也没有修改项目 `.env`。

| 当前实例 | 当前归属及数据状态 | 后续迁移前需处理 |
| --- | --- | --- |
| `chemicalops-redis-1` | 已在 `chemicalops` 项目中，原入口为本目录的 Redis 文件 | 缓存可重建；实际切换时核对端口 |
| `docker-minio-1` | RAGFlow 的 `docker` 项目，卷为 `docker_minio_data` | 核对是否被其他项目共用；备份并迁移所需桶与对象 |
| `chemicalops-qdrant` | 独立容器，未挂载数据卷 | 先生成集合快照并导出，再恢复到新持久卷；不能直接删除旧容器 |
| `chemicalops-messaging-rabbitmq-1` | 已停止的历史实例 | 不自动启动或清理，保留原数据 |

现有 MinIO、Qdrant 正占用上表端口，不能直接启动一套新实例替代它们。新配置使用独立命名卷，不会自动包含旧实例中的文件或向量。实际切换需另行安排备份、恢复和端口交接。

## 配置校验

以下命令均在项目根目录执行。凭据从现有 `.env` 读取，不写入 Compose 文件。`config --quiet` 只校验，不输出展开后的凭据，也不修改容器：

```powershell
docker compose --env-file .env -f deploy/compose.yaml config --quiet
docker compose --env-file .env -f deploy/compose.yaml config --services
```

若有部署端口差异，可在项目 `.env` 配置以下变量，并同步后端连接地址：

```dotenv
CHEMICALOPS_MINIO_API_PORT=19000
CHEMICALOPS_MINIO_CONSOLE_PORT=19001
CHEMICALOPS_QDRANT_PORT=6333
CHEMICALOPS_REDIS_PORT=6380
```

后端对应 `MINIO_ENDPOINT`、`MINIO_PUBLIC_ENDPOINT`、`QDRANT_HOST` / `QDRANT_PORT` 和 `REDIS_URL`。只调整上述容器端口变量不会自动修改后端连接配置。

## 统一管理入口

完成旧实例的数据迁移与端口交接后，或在这些端口尚未被占用的新环境中，使用：

```powershell
docker compose --env-file .env -f deploy/compose.yaml up -d
docker compose --env-file .env -f deploy/compose.yaml ps
docker compose --env-file .env -f deploy/compose.yaml logs --tail 100
```

查看和停止时始终使用同一个入口，避免只用单服务文件判断其他容器为孤立服务。停止并保留卷：

```powershell
docker compose --env-file .env -f deploy/compose.yaml stop
```

仅需单独启动某个服务时，优先在统一入口后指定服务名，例如 `up -d redis`。原 `docker-compose.redis.yml`、`docker-compose.minio.yml` 与新增 `docker-compose.qdrant.yml` 仍可通过 `-f` 使用；MinIO 入口同样需要 `--env-file .env`，默认端口为 19000 / 19001。
