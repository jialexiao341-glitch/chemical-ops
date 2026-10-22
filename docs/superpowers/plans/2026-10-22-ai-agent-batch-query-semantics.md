# Agent 与批次查询语义统一实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项实施；步骤使用复选框跟踪。

**Goal:** 统一 Agent 与批次中库存/报价只读查询的条件处理、产品候选判定、库存单位汇总和确定性摘要。

**Architecture:** 保留 Agent Runtime 与批次编排器，新增共享产品查询策略与摘要函数。两条路径在工具执行前调用共享槽位校验；候选仍通过当前授权工具取得，续答仍使用 revision 和服务端重验；所有工具调用继续经过 `agent_tools.execute_tool`。

**Tech Stack:** Python、Pydantic、SQLAlchemy、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-ai-agent-batch-query-semantics-design.md`

## Global Constraints

- 只读查询继续通过 `agent_tools.execute_tool`，并在每次调用时执行现有 RBAC 与资源范围校验。
- 不接收模型生成的 SQL、数据库 ID 或权限结论；不执行业务写操作。
- 日期或单位条件无法准确执行时，在工具调用前澄清，不得静默忽略。
- 不同计量单位分别汇总，不自动换算，也不直接相加或排名。
- 不改变 API 请求/响应或持久化格式；analytics 与 document 继续由批次执行。
- 根据项目协作规范，除非用户另行要求，本计划不包含 Git 提交步骤。

## Review Focus

- Agent 请求携带日期或单位槽位时未调用任何业务工具，并保留澄清续答所需状态。
- 批次库存和报价在相同不支持槽位下得到与 Agent 相同的澄清结果。
- 多个候选且结果被截断时不能自动全选；选择过期 revision 必须拒绝。
- 同名不同规格的既有同产品族行为与明确全选行为保持稳定，异化学品模糊命中仍须等待选择。
- 跨单位结果不得被直接合计、换算或比较；结果摘要数值必须来自完整工具 totals。

---

### Task 1: 提取共享库存候选与槽位策略

**Files:**
- Modify: `backend/app/modules/ai/candidate_resolution.py`
- Create: `backend/app/modules/ai/product_query_policy.py`
- Test: `tests/test_ai_candidate_resolution.py`

**Interfaces:**
- Produces: `unsupported_product_slots(kind: str, slots: Slots) -> tuple[str, ...]`，只报告该类工具当前无法准确执行的槽位；库存与报价日期/单位规则由同一策略维护。
- Produces: `can_aggregate_inventory(*, total_rows: int, truncated: bool, explicit_aggregate: bool, same_product_family: bool) -> bool`。截断或空候选永远返回 `False`；明确全选仅在完整非空集合返回 `True`；否则保持已登记同产品族的既有确定性汇总规则。
- Produces: `inventory_family(db: Session, rows: list[dict], keyword: str) -> bool`，保留现有名称完全匹配或同一 ACTIVE 化学品 ID 的判定。
- Reuses: `validate_selection(pending, entity, selected_id, revision)`，候选 ID 和 revision 校验契约不变。

- [x] **Step 1: 写失败测试**，覆盖库存/报价槽位检查、截断/空候选不能汇总、明确全选、同产品族和不同化学品候选边界。
- [x] **Step 2: 运行测试确认策略缺失或结果不符**：`python -m pytest tests/test_ai_candidate_resolution.py -q`；新策略实现前的断言验证已完成。
- [x] **Step 3: 实现共享纯策略及服务端产品族判定**，数据库读取只保留在 `inventory_family`，纯聚合决策不访问数据库。
- [x] **Step 4: 重跑该测试**：`python -m pytest tests/test_ai_candidate_resolution.py -q`；全部通过。

### Task 2: 在 Agent 和批次执行前统一槽位与候选处理

**Files:**
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Modify: `backend/app/modules/ai/multi_intent.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_ai_multi_intent.py`

**Interfaces:**
- Consumes: Task 1 的 `unsupported_product_slots`、`can_aggregate_inventory` 和 `inventory_family`。
- Produces: Agent 与批次在库存/报价业务工具调用前使用相同的槽位决策；各自仅负责把共享决策映射为对应的 `WAITING_INPUT` 状态和既有澄清文案/状态载荷。

- [x] **Step 1: 写跨路径失败测试**：用相同的日期/单位槽位分别驱动 Agent 和批次，断言二者均进入待澄清且没有调用业务查询工具；用相同候选集合断言二者的汇总/等待判定一致。
- [x] **Step 2: 分别运行新回归确认差异可复现**：`python -m pytest tests/test_agent_runtime.py tests/test_ai_multi_intent.py -q -k 'unsupported_product_slot or candidate_policy'`；暴露了 Agent 在执行前未处理条件的差异。
- [x] **Step 3: 接入共享策略**，在 Agent 首次规划/执行前校验结构化槽位；批次删除本地日期/单位与产品族判定分支；保留候选工具输出、版本绑定和续答时的权限重查。
- [x] **Step 4: 重跑跨路径回归**：新增用例通过且无额外业务工具调用。

### Task 3: 共享库存单位汇总与产品查询摘要

**Files:**
- Create: `backend/app/modules/ai/product_query_summary.py`
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Modify: `backend/app/modules/ai/multi_intent.py`
- Create: `tests/test_ai_product_query_summary.py`
- Test: `tests/test_ai_multi_intent.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces: `inventory_totals(results: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str], Decimal]`，仅汇总工具返回的完整 totals，不从截断明细行重新求和。
- Produces: `summarize_product_evidence(entries: Sequence[Mapping[str, Any]]) -> str`，确定性处理库存、报价、无结果和截断说明；不生成模型无法从证据推出的数字。
- Batch 的多项完成率、依赖阻塞和行动建议仍由 `multi_intent.summarize` 负责；Agent 仍由 Agent Runtime 决定完成步骤集合。

- [x] **Step 1: 写摘要失败测试**，覆盖多库存单位、截断证据、无报价和多报价明细，并断言金额/数量逐项来自工具证据。
- [x] **Step 2: 运行摘要测试确认失败**：`python -m pytest tests/test_ai_product_query_summary.py -q`；先验证了缺少摘要函数以及证据边界。
- [x] **Step 3: 提取确定性汇总和摘要**，Agent 与批次复用同一实现；删除重复的库存 totals 与单项产品结果格式逻辑，不改批次整体摘要。
- [x] **Step 4: 重跑摘要回归**：摘要与两路汇总回归通过。

### Task 4: 权限与历史行为回归

**Files:**
- Review/Test: `tests/test_ai_query_isolation.py`
- Review/Test: `tests/test_ai_multi_intent.py`
- Review/Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Reuses: Agent 与批次当前工具执行、候选 revision、历史 fingerprint 和权限重验接口；不新增持久化字段。

- [x] **Step 1: 运行完整相关回归**：计划测试加共享摘要测试全部通过（111 项）。
- [x] **Step 2: 核对关键不变量**：权限隔离、候选撤权/历史证据和任务状态相关回归均通过。
- [x] **Step 3: 检查 `git diff --check` 与最终文件差异**，未改变 API、持久化格式、STAR 或 README；未进行真实模型/浏览器验收。
