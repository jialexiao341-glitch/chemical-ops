# 采购 Agent：只读任务运行与验收

> 版本：v1.0｜日期：2026-10-03｜范围：后端只读任务 MVP，开发环境验证。

## 1. 本次交付

运行入口为 `backend/app/modules/ai/agent_runtime.py`，使用 LangGraph 的 `plan → execute → plan` 条件循环。每次模型决策接收当前授权工具 Schema、本轮已执行结果及用户输入，返回受 Pydantic 约束的一个动作。工具成功后反馈结果，模型再决定调用、追问或结束；不是预先固定库存和报价两个调用的顺序。

| 工具 | 输入与结果 | 权限与范围 |
| --- | --- | --- |
| `catalog.search_products` | 产品名称/编码关键词；产品 ID、型号、包装规格、单位、来源及截断信息 | `master.products.read`；启用产品及启用单位；最多 20 条候选；关键词中的 `%`、`_` 按文字查询 |
| `supplier_quotes.find_rfq_items` | 产品 ID，可选精确询价编号；询价明细、规格、技术要求和来源 | `procurement.rfqs.read`；当前用户可见的 `SENT/RESPONDING` 询价；最多 20 条 |
| `inventory.query_available` | 已定位产品 ID，可选仓库；分单位账面可用量、明细、警告及来源 | 原仓库权限与数据范围；最多 100 条明细，全范围合计不受截断影响 |
| `supplier_quotes.compare` | 已定位产品和询价明细 ID；有效最新报价与可比组排名 | 原询价权限与数据范围；不写比价单，不选择供应商 |

多候选由服务端强制进入 `WAITING_INPUT`。用户选择只能来自已返回候选；续跑仍需重新查询核验产品和询价明细。模型猜测 ID、使用历史步骤作为本轮完成证据、仅找到产品就宣称完成业务查询，均被拒绝。零候选允许据空结果结束，含义限定为当前授权范围无匹配对象。

只读任务不要求采购数量、用途；这些字段属于后续采购草稿阶段。最终库存/价格摘要从成功工具结果生成，模型仅指定证据步骤，不自由编写数值结论。完整来源、单位、规格和警告保留在公开轨迹中。

## 2. 模型动作协议

```json
{"action":"call_tool","tool":"catalog.search_products","arguments":{"keyword":"乙醇","limit":20}}
```

```json
{"action":"ask_user","question":"请补充产品名称或编码。"}
```

```json
{"action":"finish","evidence_steps":[2,4]}
```

使用现有兼容 OpenAI 的 `chat/completions` 适配层和 `response_format=json_object`，传入独立规划提示词；服务端严格解析 Schema，额外字段无效。不依赖模型原生 tool calling。配置模型必须支持此 JSON 响应协议；本轮 HTTP 替身验证了请求格式，未连接外部模型测任务质量。已有聊天、查询图和专用草稿接口保留各自入口，尚未合并到本循环。

## 3. 任务 API

以下均需 JWT；创建还需产品读取权限，以及库存或询价读取权限之一。

| 方法与路径（前缀 `/api/v1/ai`） | 请求 | 行为 |
| --- | --- | --- |
| `POST /agent/tasks` | `{"question":"查乙醇的库存和可比报价"}` | 新建本人任务并运行一轮；请求等待到完成、追问或失败 |
| `GET /agent/tasks/{task_id}` | 无请求体 | 回看本人任务，并重新检查历史结果的权限及资源范围 |
| `POST /agent/tasks/{task_id}/continue` | `{"question":"选分析纯这一项","revision":2,"product_id":1}` | 仅继续等待补充且版本匹配的任务；ID 示例需替换为候选实际 ID |
| `POST /agent/tasks/{task_id}/cancel` | 无请求体 | 取消本人运行或等待任务；终态任务保持原状态 |

续跑可选字段还包括 `rfq_item_id`。响应包含 `id / status / revision / reply / error_code / messages / trace`。状态为 `RUNNING / WAITING_INPUT / SUCCEEDED / FAILED / CANCELLED`；轨迹保存公开工具名、参数、结果、来源、追问、完成证据和规范化停止原因，不保存模型思维链、规划提示词或服务端异常原文。

权限变化后，可能拒绝整个历史响应，避免泄漏旧结果；库存合计记录所有参与仓库 ID，截断明细不会遗漏历史范围核验。管理员也不能读取其他用户任务。任务表会保存原始问题和工具结果，供本人回看，部署时应按业务数据管理保留期限与访问权限；此记录不受示例文件中的未来日志开关控制。

## 4. 状态、预算与并发

- 每步工具结束、追问、完成或失败后保存到 MySQL `ai_agent_tasks`。`revision` 与状态条件更新阻止重复续跑和取消后的旧响应覆盖新状态；模型网络等待期间不持有任务行锁。
- `AGENT_MAX_STEPS=12`，允许 1～24；每轮计算模型决策次数，包括追问/完成。最多 10 条用户输入；达到 100 条历史步骤后不再允许续跑。
- `AGENT_TASK_TIMEOUT_SECONDS=120`，允许 1～300；`AGENT_CONTEXT_MAX_CHARS=18000`，允许 2000～18000。模型单次输出最多 2048 token，本循环不自动重试模型请求。
- 同轮同工具同参数重复调用立即停止；连续两个无效工具请求停止。模型格式异常、未授权请求、步骤/上下文/时间超限均失败并记录规范化错误。
- 总超时可中断异步模型等待；同步数据库查询不能靠 `asyncio.timeout` 强行终止，工具完成后检查总耗时。单条 SQL/连接超时需在数据库驱动和数据库侧设置，示例中的 `AGENT_TOOL_TIMEOUT_SECONDS` 尚未实现为独立 SQL 超时。
- `AGENT_ENABLED=false` 拒绝工具目录、执行和任务运行。现有任务仍遵守访问鉴权；读取依赖工具目录，因此关闭时也不能回看完整历史。`AGENT_ALLOW_WRITE_TOOLS` 不会新增写工具。

等待任务通过数据库快照可继续，但运行进程重启/被取消时可能留下 `RUNNING`；当前没有后台执行器、租约回收或自动重跑 API。可取消遗留任务后重新发起，不能宣称已完成故障恢复或写操作幂等。

## 5. 迁移与验证

新增迁移 `036_ai_agent_tasks.sql`，同步 `database/schema.sql`；部署需先按项目迁移运行器升级到 036。本地开发库于 2026-10-03 升级前完成 MySQL 逻辑备份并成功应用迁移。

```powershell
.venv/Scripts/python.exe scripts/migrate_database.py upgrade --target 036
.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_agent_read_tools.py tests/test_ai_query_catalog_expansion.py tests/test_ai_drafts.py tests/test_ai_service.py -q --tb=short
```

2026-10-03：**84 项通过**（工具 29、运行时 19、既有相关回归 36），一条 Starlette/AnyIO 弃用提示。覆盖四工具串联、多产品/多询价追问、补充续跑、未知/写工具、伪造选择、证据来源、预算、异常脱敏、任务隐私、权限撤销、截断合计范围、取消后的旧响应和真实模型 HTTP 适配协议。工具/多数运行时测试使用隔离 SQLite 与权限/模型替身；另有一个认证任务 API 测试在本地 MySQL 事务中验证迁移表、JSON 轨迹及续跑，测试后回滚。

未重跑全量后端、前端构建或完整 RAG。测试替身验证控制流和后端规则，不代表真实模型工具选择准确率、采购任务成功率、生产组织权限或实际采购效果。

## 6. 下一步交付门

1. 配置模型跑固定任务集，单独报告工具选择、参数、澄清和任务完成质量，失败案例回放；不可用测试替身的通过数替代模型指标。
2. 工作台接入任务启动、候选选择、追问续跑、状态与来源展示，完成用户交互验收。
3. 之后实现采购草稿预览、确认凭据、二次鉴权、版本校验、幂等及故障恢复，验证 C20 后开放写能力。

阶段计划仍以 [升级方案](AI%20Agent升级方案与交付标准.md) 为准；业务口径与 C01～C20 见 [采购 MVP 规则](Agent采购MVP业务规则与验收用例.md)。本次交付可称“后端只读工具型 Agent MVP”，尚未达到完整采购辅助 Agent 的交付标准。
