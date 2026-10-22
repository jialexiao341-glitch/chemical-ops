# Agent 跨业务只读工具扩展实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 在当前仓库内逐任务实施；每个任务先写失败测试，再实现并验证。步骤使用复选框跟踪。

**Goal:** 将采购 Agent 的静态只读工具能力扩展到采购申请按编号读取和采购订单跨模块追溯，并保持当前权限、数据范围、证据与摘要契约。

**Architecture:** 保留 `agent_tools.TOOLS` 静态白名单和统一 `execute_tool` 入口，在 ToolSpec 中集中版本与风险元数据。新增两种精确编号查询，复用采购申请领域服务和现有订单追溯服务；扩展语义任务类别、启动能力校验、planner 工具约束和完成证据校验。

**Tech Stack:** Python、Pydantic、SQLAlchemy、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-agent-readonly-tool-expansion-design.md`

## Global Constraints

- 新工具只读；不加入动态导入、模型生成 SQL 或数据库 Schema/API 变更。
- 权限目录过滤仅用于路由；每次执行都由统一入口重验权限，领域服务继续重验数据范围。
- `purchase_requests.get_by_no` 只用准确申请编号；`purchase_orders.trace_by_no` 只用准确订单号。
- 申请结果不返回审批意见和内部身份字段；编号不可见与不存在不得被区分。
- 订单追溯必须复用 `order_trace.trace_purchase_order` 的逐环节授权和范围约束。
- 首批 Agent 任务仍为单一业务目标；库存/报价、Agent/批次语义及真实 PO 专用路由保持兼容。
- 不做浏览器验收、真实模型评测或性能指标声明；按用户安排并入统一验收。

## Review Focus

- **编号存在但超出用户数据范围**：与不存在返回相同的空结果，不能泄露记录是否存在。
- **任务仅有采购申请或订单读取权限**：可以启动对应查询，不要求产品目录/库存权限；其他任务仍按其必需工具拒绝。
- **订单仅有基础权限、缺少关联环节权限**：只返回追溯服务定义的 `NO_PERMISSION` 阶段，不执行受限环节查询。
- **模型调用错误工具或未提供工具证据即结束**：服务端拒绝成功完成。
- **现有库存/报价与专用订单路由**：输出、权限重验、候选消歧和完成规则不回归。

---

### Task 1: 静态工具元数据与只读领域工具

**Files:**
- Modify: `backend/app/modules/ai/agent_tools.py`
- Modify: `backend/app/modules/ai/capabilities.py`
- Modify: `backend/app/modules/ai/schema.py`
- Test: `tests/test_agent_read_tools.py`
- Test: `tests/test_ai_capability_manifest.py`

**Interfaces:**
- Consumes: 当前 `ToolSpec(name, description, permission, input_schema, output_schema, handler)` 与 `execute_tool(db, user, ToolCall)`。
- Produces: `ToolSpec.version`、`ToolSpec.risk`；`purchase_requests.get_by_no` 与 `purchase_orders.trace_by_no` 两个静态工具；其输入/输出均为 `ToolSchema` 子类。`list_tools` 和 capability manifest 从 ToolSpec 读取版本/风险元数据。

- [x] **Step 1: 为 ToolSpec 元数据与工具目录写失败测试**
  - 断言现有四项工具及两项新增工具各自报告注册的版本/风险值。
  - 断言能力清单只包含当前 permission 持有者可用的工具，且字段来自同一 ToolSpec。
- [x] **Step 2: 运行目标测试确认失败**
  - Run: `python -m pytest tests/test_ai_capability_manifest.py -q`
  - Expected: 因 ToolSpec 尚无版本/风险字段或新增工具尚未注册而失败。
- [x] **Step 3: 为申请按编号读取写权限与范围测试**
  - 覆盖有效申请、申请无匹配、记录超出申请人/部门范围、未持有 `procurement.requests.read`、额外输入字段拒绝。
  - 断言输出省略审批意见及内部身份字段，来源仅指向可见申请和明细。
- [x] **Step 4: 为订单追溯工具写权限透传测试**
  - 覆盖准确 PO 编号、无 `procurement.orders.read`、越出订单范围、逐环节缺权限时保留 `NO_PERMISSION` 且不泄露该环节记录。
  - 断言 handler 复用 `trace_purchase_order`，不复制追溯 SQL。
- [x] **Step 5: 运行工具测试确认新行为失败**
  - Run: `python -m pytest tests/test_agent_read_tools.py -q`
  - Expected: 新增工具未注册或行为不符导致失败。
- [x] **Step 6: 实现输入/输出 Schema、静态 handler、ToolSpec 元数据并统一 manifest 输出**
  - 采购申请 handler 通过现有服务查询准确编号并执行 `get_request` 范围校验；不可见和不存在统一为空结果。
  - 订单 handler 调用现有 `trace_purchase_order` 并由 Pydantic 输出模型验证结果。
  - 维持所有已有工具对外 `version="1.0"`、`risk="READ_ONLY"`。
- [x] **Step 7: 运行工具与能力目录回归**
  - Run: `python -m pytest tests/test_agent_read_tools.py tests/test_ai_capability_manifest.py -q`
  - Expected: 全部通过，既有工具行为不变。

### Task 2: Agent 路由、启动与完成证据契约

**Files:**
- Modify: `backend/app/modules/ai/schema.py`
- Modify: `backend/app/modules/ai/routing.py`
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Test: `tests/test_ai_routing.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_agent_queue_runtime.py`

**Interfaces:**
- Consumes: Task 1 的工具名、输入/输出 Schema 和权限目录。
- Produces: `Task` 新增 `purchase_request`、`order_trace`；`Understanding.agent_goal` 对应返回 `purchase_request_query`、`purchase_order_trace`；`_ensure_agent_capabilities` 与完成校验按任务类别映射对应工具。

- [x] **Step 1: 为两个新任务类别写路由 Schema 与能力校验失败测试**
  - 断言单项任务可进入 Agent 模式；模型把新业务任务指向其他执行模式或混入不支持子任务时被 Schema 拒绝。
  - 断言每个任务类别只需其映射工具；无权时拒绝执行。
- [x] **Step 2: 运行路由目标测试确认失败**
  - Run: `python -m pytest tests/test_ai_routing.py -q`
  - Expected: 因 Task Literal 和 agent 模式校验尚未扩展而失败。
- [x] **Step 3: 为独立权限启动与完成证据写运行时失败测试**
  - 仅有申请读取权限时，申请查询任务可创建并完成，不要求产品/库存权限。
  - 仅有订单读取权限时，订单追溯任务可创建并完成，不要求产品/库存权限。
  - 新任务必须有匹配的成功工具证据；缺证据、错工具和越权工具不能被 `finish` 标为成功。
  - 对准确编号无匹配的空结果可以作为已验证完成；受限订单阶段仍只能呈现 `NO_PERMISSION`。
- [x] **Step 4: 运行 Agent Runtime 目标测试确认失败**
  - Run: `python -m pytest tests/test_agent_runtime.py -q`
  - Expected: 新增用例因当前启动门禁、能力映射或 finish 规则失败。
- [x] **Step 5: 扩展 Understanding 任务类别、prompt 和 goal 映射**
  - 增加 `purchase_request`、`order_trace` 的明确路由说明和准确编号槽位约束。
  - 不将任务类型或编号由关键词捷径决定；语义理解仍使用现有结构化输出契约。
- [x] **Step 6: 调整能力预检、任务启动、执行意图校验、完成校验和确定性摘要**
  - 启动前按可执行任务类型要求最小权限；保留旧库存/报价门禁。
  - 每种新任务限定其映射工具；以当前轮成功轨迹为完成证据，允许经过 Schema 校验的空结果。
  - 申请摘要不输出未授权字段；订单摘要沿用追溯服务返回的答案和来源。
- [x] **Step 7: 运行路由、Agent、队列与订单追溯回归**
  - Run: `python -m pytest tests/test_ai_routing.py tests/test_agent_runtime.py tests/test_agent_queue_runtime.py tests/test_agent_rfq_continuation.py -q`
  - Expected: 全部通过；原有库存/报价和 PO 专用追溯测试保持通过。

### Task 3: 端到端能力目录与全量目标回归

**Files:**
- Modify: `docs/Agent功能专项排查报告.md`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_agent_read_tools.py`
- Test: `tests/test_ai_capability_manifest.py`
- Test: `tests/test_ai_query_isolation.py`
- Test: `tests/test_ai_multi_intent.py`

- [x] **Step 1: 添加跨层合同回归**
  - 使用注册目录验证每个用户可见任务恰有可执行的对应只读工具。
  - 验证撤权后任务结果/导出沿用当前访问重验，不通过历史轨迹泄露来源。
- [x] **Step 2: 运行本批完整后端回归**
  - Run: `python -m pytest tests/test_agent_runtime.py tests/test_agent_queue_runtime.py tests/test_agent_rfq_continuation.py tests/test_agent_read_tools.py tests/test_ai_capability_manifest.py tests/test_ai_routing.py tests/test_ai_query_isolation.py tests/test_ai_multi_intent.py tests/test_llm_gateway.py -q`
  - Expected: 全部通过；同步记录实际通过数与任何环境限制。
- [x] **Step 3: 运行 `git diff --check` 并更新排查报告**
  - 只有工具、路由、权限和完成契约均经回归后，才记录本批实际交付；AG-08 的超时/重试/幂等/配额治理与 AG-09 的别名/模糊实体解析继续标为未完成；不改 STAR/README。
  - 将真实模型、浏览器和性能评测保留为未验收事项。

## Plan Self-Review

- **Spec coverage:** 三个任务覆盖两项工具、静态元数据、能力清单、权限和数据范围、Agent 路由/启动/完成约束、摘要、空结果及回归边界。
- **Task dependencies:** Task 2 消费 Task 1 的工具名、Schema 和 permission 元数据；Task 3 依赖两者的接口并验证跨层一致性。
- **Risk coverage:** 越权枚举、范围限制、订单分阶段授权、错误工具/缺证据、旧库存报价和专用订单路由均有对应测试步骤。
- **Scope:** 无数据库/API 变更、写操作、动态插件、多域复合任务、浏览器验收或真实模型评测。

