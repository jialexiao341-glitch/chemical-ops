# 采购 Agent：只读任务运行说明

> 当前默认执行模式为 MySQL database 队列；可显式回退 in_process。同步任务、异步任务和业务写入边界分别说明。

异步任务使用 `AGENT_EXECUTION_MODE=database`，可显式回退为 `in_process`。四个异步入口用 MySQL 同事务保存任务、聊天关联和执行记录，公开响应仍为 202/TaskRead；队列等待仍显示 RUNNING。独立 Worker 保存运行代次、最新 revision 和已核验对象 checkpoint，中断重试更新已有助手消息；WAITING_INPUT 结束当前执行，人工续跑创建新代次，取消使旧 token 失效。排队及工具步骤重新检查用户状态、权限和来源范围。同步任务入口保持原行为，任务仍只读，不新增自动确认或业务写入。

启动、队列等待/失败查询及分阶段回滚统一见 [数据库队列运行说明](数据库任务队列运行说明.md)。已退役的 RabbitMQ 运行与验收说明不再作为当前入口；历史模型评测仍按原样本范围解释。

## 1. 运行能力

运行入口为 `backend/app/modules/ai/agent_runtime.py`，使用 LangGraph 的 `plan → execute → plan` 条件循环。每次模型决策接收当前授权工具 Schema、本轮已执行结果及用户输入，返回受 Pydantic 约束的一个动作。工具成功后反馈结果，模型再决定调用、追问或结束；不是预先固定库存和报价两个调用的顺序。

| 工具 | 输入与结果 | 权限与范围 |
| --- | --- | --- |
| `catalog.search_products` | 产品名称/编码关键词；产品 ID、型号、包装规格、单位、来源及截断信息 | `master.products.read`；启用产品及启用单位；最多 20 条候选；关键词中的 `%`、`_` 按文字查询 |
| `supplier_quotes.find_rfq_items` | 产品 ID，可选精确询价编号；询价明细、规格、技术要求和来源 | `procurement.rfqs.read`；当前用户可见的 `SENT/RESPONDING` 询价；最多 20 条 |
| `inventory.query_available` | 已定位产品 ID，可选仓库；分单位账面可用量、明细、警告及来源 | 原仓库权限与数据范围；最多 100 条明细，全范围合计不受截断影响 |
| `supplier_quotes.compare` | 已定位产品和询价明细 ID；有效最新报价、可比组排名、完整可比报价的总成本候选、交期/账期及可见验收事实风险 | 原询价权限与数据范围；质量统计服从验收读取范围；不做汇率换算、不把账期/交期/质量次数折算为金额或综合分、不确认中选 |

多候选由服务端强制进入 `WAITING_INPUT`。用户选择只能来自已返回候选；续跑仍需重新查询核验产品和询价明细。模型猜测 ID、使用历史步骤作为本轮完成证据、仅找到产品就宣称完成业务查询，均被拒绝。零候选允许据空结果结束，含义限定为当前授权范围无匹配对象。

只读任务不要求采购数量、用途；这些字段属于后续采购草稿阶段。报价工具仅在全部询价明细完整、报价可比、成本组成完整且币种一致时给出唯一最低成本候选；成本并列、截断、多币种或无合格候选时不推荐。交期、付款条件和可见质量验收统计以事实和核查提示呈现，不合成综合分，也不自动定标。最终库存/价格摘要从成功工具结果生成，模型仅指定证据步骤，不自由编写数值结论。完整来源、单位、规格和警告保留在公开轨迹中。

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

使用现有兼容 OpenAI 的 `chat/completions` 适配层和 `response_format=json_object`，传入独立规划提示词；服务端严格解析 Schema，额外字段无效。不依赖模型原生 tool calling。配置模型必须支持此 JSON 响应协议，并经服务端 Schema 校验。模型调用经过 [LLM Gateway](LLM-Gateway兼容矩阵.md)。聊天中的库存/询价请求可进入本循环，其他只读查询和专用草稿沿用各自受控入口。

### 2.1 意图、能力与执行边界

统一路由先接收当前账号的能力清单：`agent_tasks` 包含完整前置工具要求，`agent_tools` 复用工具的主权限及附加权限，`analytics_datasets` 包含可回答的原始和派生结果，`action_proposals` 区分聊天与业务页面入口。功能介绍、操作指导及统计规划均使用这份契约；能力说明不代表具体记录的权限校验已通过，执行与历史回看仍会重新核验。

同一产品的库存与报价使用一个 Agent 目标；不同独立产品使用批次。一个合法统计计划能覆盖的订单、库存与供应商关联分析保留在同一个 analytics 子任务中。规划模型收到当前可用数据集及原始条件，结构不合法时反馈校验规则并重试一次；失败后停止，不以关键词生成近似查询或悄悄恢复旧计划。

只有缺少实质业务条件时才进入澄清。请求识别的模型服务错误和结构错误分别报告 `INTENT_SERVICE_ERROR`、`INTENT_SCHEMA_ERROR`，不会作为待补充条件保存；任务运行中发生时标记 `FAILED`。真正超出当前入口能力的执行请求使用 `UNSUPPORTED_REQUEST`，不继续索要无法执行动作所需的业务编号。

采购申请创建、修改、提交以及询价草稿可按当前权限在聊天中准备提案；发送询价和中选确认从对应业务页面发起。所有动作都经过既有预览、明确确认、版本、权限和业务状态校验。要求跳过确认或执行未登记动作不会触发业务写入。

真实模型路由抽查脚本为 `scripts/evaluate_ai_routing_contract.py`，只使用合成权限与问题，不读取业务库或执行业务工具；运行会向配置的模型服务发送问题和注册能力元数据，并将结果写入指定评测 JSON。模拟回归与真实模型抽查均不代替浏览器验收。

## 3. 任务 API

以下均需 JWT；创建至少需具备一种完整的 Agent 记录读取能力。库存/报价需要产品目录定位及对应业务读取权限；按单号读取采购申请、订单、到货、验收、对账单或供应商资料不要求库存权限。具体目标在统一路由和执行时再次鉴权。

| 方法与路径（前缀 `/api/v1/ai`） | 请求 | 行为 |
| --- | --- | --- |
| `POST /agent/tasks` | `{"question":"查乙醇的库存和可比报价"}` | 新建本人任务并运行一轮；请求等待到完成、追问或失败 |
| `POST /agent/chat/start` | `{"question":"帮我查库存","conversation_id":1}`（会话可省略） | 202 启动并原子保存本人会话、输入及任务引用；响应增加 `conversation_id` |
| `POST /agent/chat/{task_id}/continue` | 与 continue 相同 | 202 续跑并追加该会话的新一轮用户/助手消息 |
| `POST /agent/tasks/start` | `{"question":"查乙醇库存"}` | 202 返回编号和 RUNNING；按配置进入数据库队列或进程内执行，供工作台轮询/取消 |
| `POST /agent/tasks/{task_id}/continue/start` | 与 continue 相同 | 版本校验后 202 返回 RUNNING；独立后台会话重新定位核验 |
| `GET /agent/tasks/{task_id}` | 无请求体 | 回看本人任务，并重新检查历史结果的权限及资源范围 |
| `POST /agent/tasks/{task_id}/continue` | `{"question":"选分析纯这一项","revision":2,"product_id":1}` | 仅继续等待补充且版本匹配的任务；ID 示例需替换为候选实际 ID |
| `POST /agent/tasks/{task_id}/cancel` | 无请求体 | 取消本人运行或等待任务；终态任务保持原状态 |

续跑可选字段还包括 `rfq_item_id`。响应包含 `id / status / revision / reply / error_code / messages / trace / conversation_id`。状态为 `RUNNING / WAITING_INPUT / SUCCEEDED / FAILED / CANCELLED`；轨迹保存公开工具名、参数、结果、来源、追问、完成证据和规范化停止原因，不保存模型思维链、规划提示词或服务端异常原文。

聊天历史返回 Agent 助手摘要前也重查任务权限，失去权限时替换为不可访问提示；原始证据不复制到聊天 citations。任务权限变化后，可能拒绝整个历史任务响应，避免泄漏旧结果；库存合计记录所有参与仓库 ID，截断明细不会遗漏历史范围核验。管理员也不能读取其他用户任务。任务表会保存原始问题和工具结果，供本人回看，部署时应按业务数据管理保留期限与访问权限；此记录不受示例文件中的未来日志开关控制。

## 4. 状态、预算与并发

- 每步工具结束、追问、完成或失败后保存到 MySQL `ai_agent_tasks`。`revision` 与状态条件更新阻止重复续跑和取消后的旧响应覆盖新状态；模型网络等待期间不持有任务行锁。
- `AGENT_MAX_STEPS=12`，允许 1～24；每轮计算模型决策次数，包括追问/完成。最多 10 条用户输入；达到 100 条历史步骤后不再允许续跑。
- `AGENT_TASK_TIMEOUT_SECONDS=120`，允许 1～300；`AGENT_CONTEXT_MAX_CHARS=18000`，允许 2000～18000。模型单次输出最多 2048 token，本循环不自动重试模型请求。
- 同轮同工具同参数重复调用立即停止；连续两个无效工具请求停止。模型格式异常、未授权请求、步骤/上下文/时间超限均失败并记录规范化错误。
- 总超时可中断异步模型等待；同步数据库查询不能靠 `asyncio.timeout` 强行终止，工具完成后检查总耗时。单条 SQL/连接超时需在数据库驱动和数据库侧设置，示例中的 `AGENT_TOOL_TIMEOUT_SECONDS` 尚未实现为独立 SQL 超时。
- `AGENT_ENABLED=false` 拒绝工具目录、执行和任务运行。现有任务仍遵守访问鉴权；读取依赖工具目录，因此关闭时也不能回看完整历史。`AGENT_ALLOW_WRITE_TOOLS` 不会新增写工具。

### 4.1 会话短期记忆 JSON

迁移 `037_ai_conversation_memory_state.sql` 在 `ai_conversation_state.memory_state` 保存每个会话的短期状态；Agent 任务快照也保存同一状态，供等待补充时恢复。新 Agent 任务还会从已鉴权的本人会话读取最近 8 条消息，补足普通化学品问答与业务 Agent 之间的指代上下文（例如先问乙醇资料，再问“它的库存”）。若上下文中只有一个明确对象，应以该名称发起本轮产品检索；若存在多个可能对象，应请用户确认。这些历史消息只用于解析检索关键词；产品仍需本轮目录检索，旧 ID、库存/报价事实不会被当作本轮证据。字段结构为：

```json
{
  "schema_version": 1,
  "turn": 2,
  "goal": {"intent": "inventory_query", "description": "查询乙醇的库存", "last_user_input": "它还有库存吗？", "status": "running"},
  "focus": {"entity_type": "product", "user_mention": "乙醇", "product_name": "无水乙醇", "product_code": "P-ETH", "resolution": "resolved", "candidates": []},
  "slots": {"warehouse": null, "unit": null, "limit": null},
  "pending": null,
  "recent_context": [{"role": "user", "text": "乙醇的库存？"}, {"role": "assistant", "text": "请提供产品名称或编码。"}],
  "evidence_ref": {"task_id": "任务引用", "trace_steps": [1]},
  "updated_at": "2026-10-03T...Z"
}
```

规划器用焦点实体、待补充问题和最近最多 8 条对话片段解析“它/刚才那个”等指代；候选只保存名称、编码和规格，不把旧产品 ID 当作可执行授权。历史对话/证据引用仅提供上下文，库存、报价及权限每轮仍由工具重新查询和鉴权。完成、等待、失败、取消都会同步相应状态。

database 模式使用持久执行记录、租约、checkpoint 与 fencing，运行故障按任务队列规则处理；in_process 模式没有跨进程自动恢复。无法确认旧执行已停止时必须隔离，不直接重放。完整边界见 [数据库队列运行说明](数据库任务队列运行说明.md)。


## 5. 工作台与运行自查

AI 工作台的聊天输入框可发起只读库存/报价任务。产品及询价歧义由候选选择或补充条件解决；后台 202 入口配合轮询和取消。历史消息保留任务引用，读取轨迹及来源时重新校验当前权限。新建/切换会话、取消任务或版本变化后，迟到响应不得覆盖当前任务。

部署使用当前数据库迁移入口，不停留在只读任务最初的 036/037 版本：

```powershell
.venv/Scripts/python.exe scripts/migrate_database.py upgrade
.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_agent_read_tools.py tests/test_agent_queue_runtime.py -q
.venv/Scripts/python.exe scripts/evaluate_agent_tasks.py --validate
```

真实模型复测需配置模型并使用独立输出路径；固定样本及历史原始证据见 [评测文件说明](evaluation/评测文件说明.md)。Mock 控制流测试不代表真实模型业务质量或生产容量。
