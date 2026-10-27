# 采购 Agent 全链路接口验收

> 后续已收敛全量失败、补齐 6 类评分器反例校验并落实 v2 基线，最终为 **1644 passed、0 failed、11 skipped**；见[评分器修复与全量结果](评分器六类漏检修复.md)。本文后续的 92 项失败列表保留为首次验收的历史证据。

## 范围与结论

本轮完成采购申请 → 询价 → 报价解析候选与人工复核提交 → 中选 → 订单草稿 → 提交审批的接口级集成验收。浏览器验收按用户要求，统一留到蓝图所有需求开发完成后进行。

这是本机开发库、合成物料和固定模型响应下的流程与规则验证，不代表真实供应商文件抽取质量、真实模型端到端行为或生产业务效果。人工复核步骤由测试显式构造复核后的报价请求；人工角色审批通过正式采购申请接口执行。订单最终停留在 `APPROVING`，不审批订单、不正式下单。

## 新增可复现用例

代码：[采购链路接口用例](../../tests/test_agent_procurement_chain.py)。

| 检查点 | 验证内容 |
| --- | --- |
| 采购申请 | 两条真实目录产品明细；提案预览不创建申请；未明确确认返回 422；他人消费提案返回 404 |
| 申请提交与审批 | 确认后进入 APPROVING；未审批来源不能准备询价提案；采购员没有审批权限；采购负责人通过正式接口审批 |
| 询价 | 从已审批申请生成草稿，确认发送后进入 SENT；所有明细关联来源申请 |
| 报价解析 | 真实 CSV 解析、逐字段原文证据核验、文件上传元数据与本地对象保存；模型接口替换为固定响应；解析后没有报价业务记录 |
| 报价人工录入 | 测试显式复核并提交数量、单位、单价、税率、交期、付款条件和来源文件；两条报价分别保留月结 30/60 天 |
| 中选 | 采购员中选提案被拒绝；有定标权限的采购负责人生成并确认中选提案 |
| 订单 | 预览不创建订单；确认创建 DRAFT；保留申请、比价、报价来源，以及逐行付款条件快照；未税 100+110 元、税率 13%，订单金额 237.30 元 |
| 提交审批 | 按准确 PO 号确认提交，只进入 APPROVING；仅一个待审批节点，没有下单日期，申请两行已采购数量仍为 0 |
| 幂等 | 链路中每个提案均重复确认，重放同一结果；申请、询价、报价和订单各增加一份 |
| 报价返回值 | 独立回归验证首版及第二版报价立即出现在录入接口返回的询价详情中 |

业务接口使用真实身份、权限、提案处理器、领域服务和 MySQL。每个 HTTP 请求使用独立 Session；业务提交只释放 SAVEPOINT，外层事务在测试结束时回滚。登录测试口令也在外层事务中回滚。原始 CSV 写入项目内的独立临时目录，测试结束后清理。

## 本轮修复

1. **录入报价后接口返回空列表**：生产 Session 配置为 `expire_on_commit=False`。录入前已经加载 `rfq.quotes`，新增 `SupplierQuote(rfq_id=...)` 不会自动更新该关联集合。现在提交后仅使 `quotes` 关联失效，再沿用既有查询装载最新列表。修复位置：[rfqs/service.py](../../backend/app/modules/rfqs/service.py)。
2. **旧确认验收夹具缺表**：旧确认入口会先查询通用提案账本，隔离库夹具此前仅创建兼容确认表。补建 `ai_agent_action_proposals`，保留原有真实写入、整体回滚、并发幂等、失败重试和响应丢失重放断言。
3. **报价人工复核单测适配**：为既有轻量 Session 替身补充 `expire` 接口，不改变原有人工修改值与成本计算断言。

报价刷新回归已执行反向验证：临时撤掉两行修复，首版报价断言失败（`[] != [1]`）；恢复修复后，链路和报价版本用例通过。

## 验证结果

- 采购专项串行回归：**203 passed**，无跳过。覆盖链路、通用提案、Inbox、采购草稿桥接/确认、询价发送/中选、订单草稿/提交、报价抽取/比较/成本、门户催办、采购并发和采购申请接口。
- 隔离 MySQL 采购确认：**5 passed**，已包含在上述专项计数中，不重复累计。使用随机独立数据库，测试后清理。
- 门户催办真实 MySQL 并发：**1 passed**。另建随机独立库，显式传入 `FOLLOWUP_TEST_MYSQL_URL`，验证 RR 隔离级别下并发发送只保存一份并重放结果；结束后仅清理该临时库。
- 报价修复恢复后再次检查：链路及报价抽取评测文件 **10 passed**。
- 清理后只读核查：链路测试产品、供应商、申请和随机隔离验收库的剩余数量均为 **0**。
- 均有同一条 Starlette / AnyIO 弃用警告，不影响断言结果。

最终后端全量复跑为 **1416 passed、92 failed、11 skipped**，共 1519 项，命令退出码 1。因此本轮只确认采购专项通过，**不放行全项目验收**。完整失败测试名称、错误摘要及计数见[结构化验收证据](procurement-chain-acceptance.json)。

| 失败文件 | 项数 | 当前观测 |
| --- | ---: | --- |
| `test_agent_queue_runtime.py` / `test_agent_rfq_continuation.py` | 11 | SQLite 夹具建表已有 7 列，部分询价行仍使用 5 值的无列名 INSERT |
| `test_business_evaluation_metrics.py` | 70 | 20 项为产品/询价行 INSERT 与当前夹具列数不匹配；50 项为评测预期断言失败，仍需逐项定位 |
| `test_agent_read_tools.py` / `test_agent_task_evaluation.py` | 2 | 新增补货工具后，旧工具清单/数量断言未同步 |
| `test_ai_conversation_delete.py` / `test_ai_query_isolation.py` / `test_ai_task_management.py` | 3 | 会话存在性、报价统计数量、任务分页数量断言失败，仍需单独定位 |
| `test_evaluation_fixtures.py` | 1 | 冻结评测清单完整性校验不一致 |
| `test_exception_action_decision.py` | 1 | 用例引用不存在的 `_validate_assignee` |
| `test_finance_difference_checks.py` | 1 | 单证复核检查断言失败，仍需单独定位 |
| `test_procurement_state_machines.py` | 1 | 用例提交报价缺少必填 `currency_code`，接口返回 422 |
| `test_supplier_portal_api.py` | 2 | 门户订单响应的 `tax_included` 字段校验失败 |

这些结果是独立全量回归的现状记录；没有通过原始代码基线对比的失败，不直接归因为本轮修改或既有问题。本轮未修改这些模块的业务行为，也没有放宽断言来取得全量通过。

11 个跳过项分别为未显式配置隔离 URL 的门户催办并发 1 项、Redis 专项 8 项、真实 MinIO 验收 1 项、显式 Worker 故障演练 1 项。其中门户催办并发已另在隔离库补跑通过，其余跳过项不计为通过。

专项复现命令（项目根目录，需可连接本机 MySQL）：

```powershell
.venv/Scripts/python.exe -m pytest -q -rs --tb=short tests/test_agent_procurement_chain.py tests/test_ai_action_proposals.py tests/test_ai_action_handlers.py tests/test_ai_action_proposal_inbox.py tests/test_ai_purchase_draft_bridge.py tests/test_ai_purchase_draft_confirmations.py tests/test_ai_purchase_draft_mysql_acceptance.py tests/test_ai_rfq_send_action.py tests/test_ai_rfq_select_quote_action.py tests/test_ai_purchase_order_action.py tests/test_ai_purchase_order_submit_action.py tests/test_purchase_order_draft_action.py tests/test_purchase_order_quote_loading.py tests/test_rfq_quote_extraction.py tests/test_quote_extraction_evaluation.py tests/test_rfq_quote_comparison.py tests/test_rfq_quote_recommendation.py tests/test_rfq_total_cost.py tests/test_delivery_followup_portal.py tests/test_procurement_concurrency.py tests/test_purchase_requests_api.py
```

连接同一开发库的集成测试应串行运行。曾同时运行全量与专项回归，导致登录计数表锁竞争；停止重叠运行后，专项串行复跑通过。该竞争不计作功能验收结果。

## 放行边界

采购接口链路专项通过不等于后端全量回归通过。完整回归结果及逐项失败清单另存结构化证据；尚未解决的全局回归失败不得记为通过。

仍待完成：真实供应商文件及真实模型业务链路验收、全局回归失败收敛，以及蓝图需求全部开发完成后的统一浏览器验收。其他列表上下文、跨用户待办、统一文档入口和运营闭环按蓝图第 10.1 节继续推进。
