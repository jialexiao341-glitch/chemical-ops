# AI 查询与意图识别设计

## 支持的意图

后端在进入大模型和数据库查询链之前先识别意图：

| 意图 | 处理方式 |
| --- | --- |
| 查询咨询意图 | 进入 Text2SQL；只允许白名单数据集、指标、维度、筛选字段和时间字段 |
| 了解项目的功能意图 | 返回项目当前 AI 能力说明 |
| 打招呼意图 | 返回固定问候 |
| 其他问题 | 明确提示暂不支持，例如天气、新闻、股票、旅游和娱乐内容 |

意图词表位于 `backend/app/modules/ai/intent.py`。项目功能意图优先于通用查询词；带附件的请求保留进入 MinerU/文档解析链，避免误拦截文档分析。

## Text2SQL 目录与提示词

- `backend/app/modules/ai/catalog.py`：数据集、数据库表、指标、维度、筛选字段、时间字段和读取权限映射。
- `backend/app/modules/ai/agent_prompt.py`：Agent 系统提示词和 Text2SQL Query Plan 提示词。
- `backend/app/modules/ai/text2sql.py`：LangGraph 查询流程、ORM SQL 生成、SQL 校验、权限校验和结果序列化。
- `POST /api/v1/ai/text2sql`：只读自然语言查询接口。

模型只能返回结构化 Query Plan，后端不执行模型返回的原始 SQL。后端会依次执行 Query Understanding、Slot Filling、Query Planning、SQL Validation 和 Execution；SQL 必须是 SELECT，只能访问当前数据集的表白名单，且最终权限由当前用户的 RBAC 权限决定。

## 明确限制

AI 不能创建或修改采购申请、采购订单、入库单、付款单等数据，也不能审批、提交、下单、入库、出库或执行库存操作。当前查询结果仍受数据权限和行数上限限制；尚未开放全历史数据保证和任意 SQL 查询。

## 查询链路输出

Text2SQL 查询会同时返回用户 Query、已抽取槽位、查询模板、生成并校验后的 SQL、清洗后的 JSON 行数据、列渲染元数据、执行阶段和截断状态。聊天接口将同一份 query_trace 放入 API 响应和持久化 citation，前端据此展示查询链路、槽位、SQL、JSON 和结果表，不依赖从自然语言答案中反向解析。

持久化分两层：`ai_conversation_state.query_trace` 只保留每个会话最近一次查询（用于多轮追问衔接），`ai_query_log`（迁移 020）按轮追加留档槽位、模板、SQL 和行数，用于历史回溯；迁移未执行时留档自动跳过，不影响查询主链路。
