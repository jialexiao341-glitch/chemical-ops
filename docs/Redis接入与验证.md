# Redis 接入与验证

## 启动与配置

Redis 仅保存可重建缓存和短期限流计数，MySQL 继续保存消息、上下文和任务状态。不使用 Redis 替换数据库任务队列或正式 Checkpointer。

安装 `backend/requirements.txt` 后，在项目根目录启动独立实例：

```powershell
docker compose --env-file .env -f deploy/compose.yaml up -d --wait redis
```

项目端口为 **6380**，仅绑定 `127.0.0.1`，容器内部仍为 6379。与其他项目的 6379 实例分开。Compose 中不启用 RDB/AOF；Redis 重启后缓存回源，限流窗口重新计数。需要修改宿主端口时，设置 `CHEMICALOPS_REDIS_PORT` 并同步修改 `REDIS_URL`。

在本地 `.env` 中设置，并重启后端 API 和任务 worker：

```dotenv
REDIS_ENABLED=true
REDIS_RATE_LIMIT_ENABLED=true
REDIS_URL=redis://127.0.0.1:6380/0
REDIS_KEY_PREFIX=chemicalops
REDIS_TIMEOUT_SECONDS=0.3
REDIS_CACHE_TTL_SECONDS=300
REDIS_SESSION_TTL_SECONDS=60
AI_RATE_LIMIT_REQUESTS=30
DOCUMENT_RATE_LIMIT_REQUESTS=5
RATE_LIMIT_WINDOW_SECONDS=60
```

不同部署使用独立的 `REDIS_KEY_PREFIX`；键中同时包含 `APP_ENV` 和协议版本。带认证或 TLS 的 Redis 使用相应 `redis://用户名:密码@主机:端口/数据库` 或 `rediss://…` URL。示例 Compose 用于本机开发。

新环境默认关闭两个开关，兼容未启动 Redis 的安装。缓存可单独启用；启用限流必须同时启用 Redis，否则配置校验失败。关闭缓存时也应关闭限流开关。

## 接入范围

| 能力 | 接入位置 | 规则 |
| --- | --- | --- |
| 商品基础信息 | `GET /products/{product_id}` | 缓存 `ProductRead` 快照；写业务仍读取 ORM 实体 |
| 商品候选及 CAS 查询 | Agent 的 `catalog.search_products`，名称、完整编码和有效 CAS 查询 | 缓存候选、总数和来源，不缓存库存或供应商报价；工具执行入口仍校验当前权限 |
| 热点会话历史 | `conversation_store.list_messages` | 按用户、会话和条数隔离，缓存原始消息；归属检查先于缓存，历史证据检查后于缓存 |
| AI 用户级限流 | `/ai` 下的计算类 POST 请求，包括路由、工具执行、普通聊天、SSE、Agent 启动和继续 | 每用户共享 AI 配额；路由理解和后续执行分别计一次；GET、取消、重命名、删除及清空上下文不消耗配额 |
| 文档用户级限流 | 技术资料 `fetch`、`ingest`，质量验收 `report-review` | 每用户共享文档配额，与 AI 配额独立；后台重试不再次扣入口配额 |

普通文件上传不属于解析入口，不消耗文档配额。聊天中的附件解析受 AI 入口配额保护。会话状态、Agent 检查点和理解模型的上下文读取仍以数据库为准；本阶段只缓存历史消息分页。

## 一致性与故障行为

- Cache Aside：未命中时查询数据库并保存已校验 JSON；命中时验证快照结构。损坏数据回源，超过 1 MiB 的快照不缓存。
- 通过 SQLAlchemy Session 的 ORM 写入及结构化 INSERT/UPDATE/DELETE，在最外层事务提交后使关联缓存失效；回滚不失效，保存点释放不提前失效。事务有待提交修改时绕过缓存。
- 主数据和消息历史分别使用一个版本命名空间。产品、化学品或单位修改使主数据缓存整体失效；消息或会话修改使历史缓存整体失效。不扫描缓存键。并发旧读取回填在旧版本下，不能覆盖新版本快照。
- 库存、报价、资源归属及权限判断不缓存。会话历史命中后继续执行现有 `visible_message` 与文档来源状态检查。
- Redis 连接、读取或写入失败时，缓存回源数据库。提交成功但缓存失效失败时记录指标和警告，旧数据最多保留到原 TTL；绕过应用直接执行原生 SQL 或外部脚本修改数据，也依赖 TTL 或显式执行缓存失效。缓存不提供跨系统强一致性。
- 限流使用 Lua 原子完成计数、判断和过期，窗口从首次获准请求起算，拒绝请求不续期。达到配额返回统一 HTTP 429 和 `Retry-After`；Redis 故障返回 503，不使用各进程独立的内存计数放行。SSE 在打开流之前检查。
- 固定窗口限制每个窗口内的数量，不承诺任意滑动时间区间或同时运行任务数的上限；后者仍由现有任务 worker 并发配置控制。

## 验证与复现

`tests/test_redis_features.py` 包含故障策略测试及真实 Redis 集成。未设置 `TEST_REDIS_URL` 时，真实集成用例跳过；设置后连接失败会使测试失败。每个用例使用随机键前缀，只清理自己创建的键，不执行 `FLUSHDB`。

```powershell
$env:TEST_REDIS_URL='redis://127.0.0.1:6380/0'
$env:REDIS_VALIDATION_REPORT='docs/evidence/redis-validation.json'
.venv/Scripts/python.exe -m pytest tests/test_redis_features.py -q
```

测试覆盖：两个用户各 100 个并发请求，各精确放行 17 个；文档配额独立；窗口过期恢复；SSE 入口 429；提交失效、事务回滚、保存点、并发旧回填、损坏缓存；会话缓存过期恢复、Redis 故障回源、用户隔离与权限撤销后的历史过滤。

[原始延迟与命中率样本](evidence/redis-validation.json)使用 5,001 条合成产品记录、同一 CAS、单线程各 100 次查询，数据库为内存 SQLite，Redis 为本机 Docker 实例。缓存组首次未命中，随后 99 次命中；SELECT 从 300 次降为 3 次。平均耗时和 P95 保存在原始 JSON 中，不作为生产 MySQL 性能或实际业务收益指标。

运行指标沿用现有受保护的指标接口，低基数标签不包含用户或查询正文：

- `chemicalops_redis_cache_count`：按 `space`、`result` 统计命中、未命中、故障及失效错误；命中率为 `hit / (hit + miss)`。
- `chemicalops_cached_read_seconds_histogram`：缓存命中和回源路径的耗时分布。
- `chemicalops_rate_limit_count`：按 AI／文档类别统计放行、拒绝和不可用。

这些指标是进程级统计，多 worker 部署需汇总各 worker。Redis 故障期间的回源请求单独计为 `unavailable`，不计入命中率分母。
