# ChemicalOps 容器配置

项目使用的容器配置集中在本目录，`compose.yaml` 是统一入口，Compose 项目名为 `chemicalops`。单服务文件通过 `extends` 复用统一定义，不再单独维护一套配置。

| 服务 | 默认宿主地址 | 数据保存方式 |
| --- | --- | --- |
| MinIO API | `127.0.0.1:19000` | 命名卷 `chemicalops_minio_data` |
| MinIO 控制台 | `127.0.0.1:19001` | 与 API 共用数据 |
| Qdrant | `127.0.0.1:6333` | 命名卷 `chemicalops_qdrant_data` |
| Redis | `127.0.0.1:6380` | 可重建缓存，不启用 RDB/AOF |
| minio-init | 无宿主端口 | 创建三个配置的私有桶，完成后退出 |

表中的卷名是 Compose 逻辑名，默认实际名称由 `chemicalops` 项目名前缀生成。本机迁移使用 `compose.existing-data.yaml` 复用原 MinIO 卷。

MySQL 继续由项目 `.env` 中的连接配置指向现有本机实例。异步任务使用 MySQL 持久队列，RabbitMQ 已退役，故不纳入本配置。其他项目的 Elasticsearch、Neo4j 等容器也不在管理范围内。

## 本机容器分组与数据

本机 Redis、MinIO、Qdrant 统一由 `chemicalops` Compose 项目管理，在 Docker Desktop 中显示为同一可展开分组。前后端与 MySQL 继续采用现有本机启动方式。

| 当前实例 | 数据与网络 | 回退保留 |
| --- | --- | --- |
| `chemicalops-redis-1` | 保留原端口与缓存配置 | 缓存可重建 |
| `chemicalops-minio-1` | 复用 `docker_minio_data`；保留 `docker_ragflow` 网络及 `minio`、`docker-minio-1` 别名 | `chemicalops-minio-rollback` 停止保留 |
| `chemicalops-qdrant-1` | 原数据复制到持久卷 `chemicalops_chemicalops_qdrant_data` | `chemicalops-qdrant-rollback` 停止保留原容器数据 |
| `chemicalops-messaging-rabbitmq-1` | 已停止的历史实例 | 不启动或清理 |

迁移前停止写入并备份了两个服务的完整数据目录，备份位于 `storage/container-backups/`（不提交 Git）。旧容器仅供回退，不应与新服务同时启动；旧 MinIO 与新 MinIO 共用同一数据卷。不要删除数据卷或使用 `down -v`。

**本机后续管理必须同时指定两个配置文件**，否则 MinIO 会使用默认的新卷且缺少 RAGFlow 网络：

```powershell
docker compose --env-file .env -f deploy/compose.yaml -f deploy/compose.existing-data.yaml up -d redis qdrant minio
docker compose --env-file .env -f deploy/compose.yaml -f deploy/compose.existing-data.yaml ps
docker compose --env-file .env -f deploy/compose.yaml -f deploy/compose.existing-data.yaml stop
```

`compose.existing-data.yaml` 依赖本机已有的 `docker_minio_data` 卷和 `docker_ragflow` 网络，其他环境使用默认统一入口即可。不要重新从 RAGFlow 原 Compose 文件启动旧 MinIO 服务，以免争用端口及数据卷。

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

## 新环境统一管理入口

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
