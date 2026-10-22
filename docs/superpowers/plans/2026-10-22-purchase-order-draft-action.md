# 中选报价生成采购订单草稿 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在询价详情中以版本化确认提案把已确认中选报价生成为采购订单草稿，并在提案预览中展示可追溯的条款核对结果。

**Architecture:** 复用采购订单领域服务的来源校验和通用 Agent 动作提案账本。订单付款条件按采购订单明细逐行快照；新增迁移只添加可空字段。提案确认通过 `create_order(..., commit=False)` 在提案事务中写入 `DRAFT`，前端替换当前直接写接口按钮并复用提案预览/Inbox 模板。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Pydantic、Alembic-free SQL migrations、Vue 3、TypeScript、Ant Design Vue、pytest、vue-tsc。

**Spec:** `docs/superpowers/specs/2026-10-22-purchase-order-draft-action-design.md`

## Global Constraints

- “不自动提交订单审批、不审批、不正式下单、不生成催货动作，也不引入模型自动判断合同合规性。”
- “使用逐行字段是因为付款条件目前存储在 `supplier_quote_items`，同一个报价中的不同明细可以有不同条件。”
- “RFQ ID、供应商、产品、价格、税率、数量和付款条件全部从服务端重新读取，不接受客户端覆盖。”
- “自动条款检查只做字段一致性、来源完整性和缺项提示；不制定付款/交期风险权重，不自动判断合规。”
- “新迁移只新增可空字段，不回填历史订单、不修改旧迁移 checksum。”
- 前端必须沿用 RFQ 详情、现有订单表单和 Agent 提案预览/确认模板；未进行浏览器验收时必须说明。

## Review Focus

- 订单创建事务由提案框架拥有：flush、编号生成、事件和审计日志不得提前提交；回滚时业务数据和提案结果一起回滚。
- 确认后来源仍可能并发变化：比价/报价状态、申请剩余量、重复订单唯一约束必须在确认事务内重验。
- 来源资源越权或权限撤销：提案 Inbox、详情与深链不得泄露供应商、金额、付款条件或报价内容。
- 多报价行的付款条件可能不同或为空：订单必须逐行保留原文，不能折叠/推断；历史订单 NULL 不得伪装成当时快照。
- 交期与缺失合同字段：只有两端日期均有值时比较；地址、预计到货日、付款条件缺失时提示但不擅自阻塞/补值。

---

### Task 1: 订单行付款条件快照与可回滚领域服务

**Files:**
- Create: `database/migrations/058_purchase_order_payment_terms_snapshot.sql`
- Modify: `backend/app/modules/purchase_orders/model.py`
- Modify: `backend/app/modules/purchase_orders/schema.py`
- Modify: `backend/app/modules/purchase_orders/service.py`
- Test: `tests/test_purchase_order_draft_action.py`

**Interfaces:**
- Consumes: `PurchaseOrderCreate(comparison_id, quote_id, delivery_address, expected_arrival_date, note)` and existing `_validate_source`.
- Produces: `PurchaseOrderItem.payment_terms_snapshot: str | None`; `create_order(db, user, data, *, commit: bool = True)` whose false branch flushes/returns the order without committing and copies each selected `SupplierQuoteItem.payment_terms` to its matching order line.

- [ ] **Step 1: Write failing domain and migration contract tests**

  Add tests proving: each order line preserves its matching source quote line's different `payment_terms`; missing terms remain `None`; `commit=False` leaves transaction uncommitted while making the created order available to the caller; default invocation preserves the existing commit behavior. Assert `scripts.migrate_database._migration_files()` discovers version `058`, and the migration SQL only adds the nullable snapshot column without data backfill.

- [ ] **Step 2: Run tests to verify they fail**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_purchase_order_draft_action.py -q --tb=short`
  Expected: FAIL because `payment_terms_snapshot` is absent and/or `create_order` does not accept `commit`.

- [ ] **Step 3: Add the additive migration and model/schema field**

  Add nullable `payment_terms_snapshot VARCHAR(255)` to `purchase_order_items` in migration 058. Add the optional field to the ORM model and `PurchaseOrderItemRead`; leave existing rows NULL and do not alter prior migrations.

- [ ] **Step 4: Add transactional service mode and snapshot copy**

  Change `create_order` to accept keyword-only `commit=True`. Always flush before assigning the business PO number and appending event/audit data; commit and refresh only when true. Copy the selected quote line's payment terms to the generated order item. Translate the source-comparison unique-constraint collision to `DuplicateResourceError` without unconditionally rolling back a caller-owned transaction.

- [ ] **Step 5: Run domain tests and related concurrency regressions**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_purchase_order_draft_action.py tests/test_procurement_concurrency.py -q --tb=short`
  Expected: PASS; existing concurrent duplicate-order protection remains intact.

- [ ] **Step 6: Commit the domain slice**

  Commit message: `feat(purchase-orders): 保存报价付款条件快照并支持事务执行`

### Task 2: Versioned order-draft action and Inbox lifecycle

**Files:**
- Modify: `backend/app/modules/ai/action_handlers.py`
- Modify: `backend/app/modules/ai/action_proposals.py`
- Modify: `backend/app/modules/ai/capabilities.py`
- Test: `tests/test_ai_purchase_order_action.py`
- Test: `tests/test_ai_action_proposal_inbox.py`
- Test: `tests/test_ai_capability_manifest.py`

**Interfaces:**
- Consumes: Task 1's `create_order(..., commit=False)`; `PurchaseOrderCreate`; existing `RFQSelectQuoteHandler`, proposal snapshot helpers and `_proposal_read`/revision conventions.
- Produces: registered `purchase_order.create_draft` handler with permission `procurement.orders.write`, business-page capability entry, `INBOX_ACTION_TYPES` inclusion, preview/read/revise behavior and an execution result serialized as `PurchaseOrderRead` JSON.

- [ ] **Step 1: Write failing handler and capability tests**

  Cover valid confirmed comparison preview without writes; reject unconfirmed/not-selected quote, unapproved source request, duplicate order, incomplete item coverage, insufficient remaining quantity, inaccessible RFQ and invalid extra payload fields; verify required write/read permissions and capability manifest entry.

- [ ] **Step 2: Run tests to verify they fail**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_ai_purchase_order_action.py tests/test_ai_capability_manifest.py -q --tb=short`
  Expected: FAIL because the action handler and capability entry are not registered.

- [ ] **Step 3: Implement source snapshot and clause-check preview**

  Add `PurchaseOrderCreateDraftHandler` in `action_handlers.py`. Accept only comparison/quote IDs and delivery address/expected date/note. Re-read the confirmed comparison, selected quote, RFQ, approved source request and line references; reuse the order service's source rules without writing. Snapshot all source fields used to construct the order. Produce line-level diff/evidence for product, quantity/unit, price, tax, currency, lead time, payment terms and RFQ/request delivery expectations. Report absent address/date/quote terms as warnings, and compare delivery dates only when both exist.

- [ ] **Step 4: Implement current-state revalidation and execution**

  Rebuild and compare the resource snapshot during preview read, revision and confirmation; recheck duplicate-order state and source quantity under the confirmation transaction. Execute `create_order(..., commit=False)` and serialize `PurchaseOrderRead`.

- [ ] **Step 5: Add capability and Inbox handling**

  Register the action as `business_page`; require `procurement.orders.write` plus the source RFQ/quote read permission. Add owner-scoped Inbox visibility and revision support limited to delivery address, expected arrival date and note. Hide diff/evidence/revision values and deep links when required permissions or RFQ scope are unavailable. Deep-link to the source RFQ.

- [ ] **Step 6: Run action and Inbox regression tests**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_ai_purchase_order_action.py tests/test_ai_action_proposal_inbox.py tests/test_ai_capability_manifest.py tests/test_ai_action_proposals.py -q --tb=short`
  Expected: PASS, including permission revocation, resource invalidation, idempotent replay and version checks.

- [ ] **Step 7: Commit the action slice**

  Commit message: `feat(ai): 接入中选报价生成订单草稿提案`

### Task 3: RFQ detail proposal flow and order result display

**Files:**
- Modify: `frontend-design/apps/web-chemicalops/src/views/procurement/rfqs/modules/detail.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/procurement/rfqs/modules/order-draft-proposal.ts`
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/ActionProposalDetail.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/index.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/api/procurement/purchase-orders.ts` to expose the line snapshot; `rfqs.ts` only if new RFQ types are needed
- Modify: `frontend-design/apps/web-chemicalops/src/api/ai/agent.ts` only if proposal result types are needed
- Test: `frontend-design/apps/web-chemicalops/src/views/procurement/rfqs/modules/detail.test.ts`; retain existing `frontend-design/apps/web-chemicalops/src/views/ai/workspace/action-proposal-policy.test.ts` regressions.

**Interfaces:**
- Consumes: Task 2's action type and preview/read contract; existing `createActionProposalApi`, `confirmActionProposalApi`, `canConfirmActionProposal` and RFQ detail template.
- Produces: confirmed selected quote exposes “检查条款并准备订单草稿”; preview renders diff/evidence/warnings and requires explicit confirmation; successful response presents the generated PO number and navigates to an existing order entry.

- [ ] **Step 1: Add a focused RFQ detail interaction test**

  Assert that creating an order proposal calls `createActionProposalApi('purchase_order.create_draft', ...)`, does not call `createPurchaseOrderApi`, and confirmation uses the preview version before showing the returned PO number.

- [ ] **Step 2: Run the frontend test to verify it fails**

  Run: `pnpm exec vitest run src/views/procurement/rfqs/modules/detail.test.ts`
  Expected: FAIL because the current button calls the direct purchase-order write API.

- [ ] **Step 3: Replace direct creation with proposal preview and confirmation**

  Preserve the existing permission and confirmed-selection visibility conditions. Show source-backed terms, warnings, and diffs using current RFQ detail and proposal UI patterns. Confirm only through `confirmActionProposalApi`; after success show `po_no` and use an existing order route. Remove only the now-unused direct-call import/handler.

- [ ] **Step 4: Support Inbox revision for the allowed order fields**

  Extend the existing proposal detail view with the current form controls/template for `delivery_address`, `expected_arrival_date` and `note`; revision must refresh the preview version and leave confirmation explicit.

- [ ] **Step 5: Run frontend verification**

  Run from `frontend-design/apps/web-chemicalops`: `pnpm exec vue-tsc --noEmit --skipLibCheck` and `pnpm exec vitest run src/views/procurement/rfqs/modules/detail.test.ts src/views/ai/workspace/action-proposal-policy.test.ts`.
  Expected: exit 0; existing unrelated failures, if present, are recorded separately.

- [ ] **Step 6: Commit the UI slice**

  Commit message: `feat(rfqs): 通过确认提案生成采购订单草稿`

### Task 4: Schema docs and feature status

**Files:**
- Modify: `docs/数据库设计说明.md`
- Modify: `docs/企业级Agent功能蓝图与业务AI打通方案.md`
- Modify: `docs/Agent功能专项排查报告.md`

**Interfaces:**
- Consumes: Tasks 1–3 implementation and verified test results.
- Produces: documented order-line payment snapshot, F-08 progress/status, and remaining browser/full-chain acceptance items.

- [ ] **Step 1: Update only directly affected documentation**

  Document nullable `purchase_order_items.payment_terms_snapshot`, F-08 order draft/terms-check scope, and leave order approval, delivery follow-up and browser acceptance marked pending. Do not edit the STAR document or README.

- [ ] **Step 2: Verify documentation diff**

  Run: `git diff --check` and inspect all three changed sections.
  Expected: no whitespace errors; no status claim exceeds implemented/tested behavior.

- [ ] **Step 3: Commit documentation**

  Commit message: `docs(agent): 回填订单草稿与条款检查进度`

### Task 5: Final verification and review

**Files:** all implementation files from Tasks 1–4.

**Interfaces:** Consumes all task outputs; produces final verification evidence and review findings.

- [ ] **Step 1: Run focused backend regressions**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_purchase_order_draft_action.py tests/test_ai_purchase_order_action.py tests/test_ai_action_proposal_inbox.py tests/test_ai_capability_manifest.py tests/test_ai_action_proposals.py tests/test_procurement_concurrency.py -q --tb=short`
  Expected: PASS.

- [ ] **Step 2: Run the full backend suite**

  Run: `.venv\Scripts\python.exe -m pytest -q --tb=short`
  Expected: record the exact count and every failure; do not claim full-suite success if the known async queue/loopback environment stalls or existing failures remain.

- [ ] **Step 3: Run frontend typecheck and focused UI tests**

  Run from `frontend-design/apps/web-chemicalops`: `pnpm exec vue-tsc --noEmit --skipLibCheck` and `pnpm exec vitest run src/views/procurement/rfqs/modules/detail.test.ts src/views/ai/workspace/action-proposal-policy.test.ts`.
  Expected: exit 0 for typecheck; record test results and environment limitations separately.

- [ ] **Step 4: Verify migration discovery and clean diff**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_purchase_order_draft_action.py -q --tb=short`, then `git diff --check` and `git status --short`.
  Expected: migration 058 is discovered, old migration checksums remain untouched, and only intended changes remain.

- [ ] **Step 5: Self-review the complete change range**

  Review all commits since the feature start for authorization, resource scope, transaction atomicity, duplicate creation, data snapshot semantics, UI template reuse and accurate pending status. Browser acceptance remains deferred as specified.
