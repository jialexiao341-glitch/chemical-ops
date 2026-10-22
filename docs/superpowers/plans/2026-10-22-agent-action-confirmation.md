# Agent 动作确认与采购闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 建立服务端通用 Agent 动作提案与确认机制，并完成采购申请修改/检查/提交及询价草稿创建的确认式闭环。

**Architecture:** 新增持久化动作提案账本与服务端白名单处理器。提案保存规范化 payload、预览版本和资源快照；确认时重验权限、范围、版本和状态，再调用支持事务内 flush 的领域服务，并与执行结果原子提交。采购申请与询价作为首批处理器，Agent 只生成建议，前端负责明确确认。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、MySQL/InnoDB、Alembic 风格 SQL 迁移、Vue 3、TypeScript、Vben/Ant Design Vue。

**Spec:** [2026-10-22-agent-action-confirmation-design.md](../specs/2026-10-22-agent-action-confirmation-design.md)

## Global Constraints

- 业务写入只能在用户确认当前预览版本后发生，并且只能通过已有领域服务完成。
- 动作类型必须在服务端注册表白名单中；模型和客户端不得指定任意服务、模块或 SQL。
- 确认时重新检查权限、用户有效状态、数据范围、对象版本和业务状态。
- 领域数据与 `EXECUTED` 结果必须在同一数据库事务提交；相同确认并发执行最多写入一次。
- 采购申请修改仅允许 DRAFT/REJECTED；询价来源申请必须可见且为 APPROVED。
- 复用现有前端模板；本期不做浏览器验收，待统一验收。

## Review Focus

- 旧版采购申请预览令牌在切换期间仍可确认；新令牌仅进入通用账本。覆盖 Task 3 兼容与重放测试。
- 空字段、非法字段和缺少必填项不得形成可执行提案。覆盖 Task 3 Schema 与阻塞项测试。
- 提案后权限撤回、用户停用或资源超范围必须拒绝确认。覆盖 Task 2 与 Task 3 授权测试。
- 提案后申请、来源申请、产品、单位或供应商状态/内容变化必须拒绝旧预览。覆盖 Task 3 与 Task 4 过期快照测试。
- 并发或重放确认只能产生一次业务写入，且回传同一结果。覆盖 Task 2 幂等测试及 MySQL 集成验收。

---

### Task 1: 动作提案数据模型、迁移与契约 Schema

**Files:**
- Create: `database/migrations/054_ai_action_proposals.sql`
- Modify: `backend/app/modules/ai/model.py`
- Modify: `backend/app/modules/ai/schema.py`
- Test: `tests/test_ai_action_proposals.py`

**Interfaces:**
- Produces: `AIAgentActionProposal` ORM model and strict `AIActionProposalCreate`, `AIActionProposalRevise`, `AIActionProposalConfirm`, `AIActionProposalPreview` schemas.
- Proposal statuses: `PENDING`, `EXECUTED`, `EXPIRED`, `CANCELLED`, `INVALIDATED`.
- Confirm input requires literal `confirm=True` and strict positive `preview_version`.

- [x] **Step 1: Write schema and persistence contract tests**

Add `test_action_proposal_confirm_requires_literal_true_and_current_version`, `test_action_proposal_schemas_forbid_extra_fields`, and `test_action_proposal_model_declares_unique_confirmation_and_idempotency_keys`.

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `pytest tests/test_ai_action_proposals.py -q`
Expected: FAIL because the generic proposal schemas/model are not defined.

- [x] **Step 3: Add the SQL migration and ORM model**

Create the proposal table with owner, action/resource identifiers, preview version, payload/hash, expected resource snapshot, diff/evidence, permission/risk, confirmation ID, idempotency key, expiry, status, result, and timestamps. Add unique constraints for confirmation ID and per-user idempotency key, plus owner/status indexes.

- [x] **Step 4: Add strict request and response schemas**

Define action type as a bounded string validated later against the server registry; set `extra="forbid"` on all write request schemas. Preview response includes diff, evidence, warnings, blockers, expiry, version, and whether confirmation is available.

- [x] **Step 5: Run the focused tests and confirm they pass**

Run: `pytest tests/test_ai_action_proposals.py -q`
Expected: PASS.

### Task 2: 通用提案服务与事务执行边界

**Files:**
- Create: `backend/app/modules/ai/action_proposals.py`
- Create: `backend/app/modules/ai/action_handlers.py`
- Modify: `backend/app/modules/ai/controller.py`
- Test: `tests/test_ai_action_proposals.py`

**Interfaces:**
- `propose_action(db, user, action_type, payload) -> AIActionProposalPreview`
- `revise_action(db, user, confirmation_id, preview_version, payload) -> AIActionProposalPreview`
- `cancel_action(db, user, confirmation_id, preview_version) -> None`
- `confirm_action(db, user, confirmation_id, preview_version, confirm=True) -> dict`
- Handler protocol: `prepare`, `validate_current`, and `execute(db, user, proposal, *, commit=False)`.

- [x] **Step 1: Add failing lifecycle tests**

Add tests for preview-only creation, exact-version confirmation, expiry, payload hash tampering, revoked permission, cancel, replay returning saved result, and handler allowlist rejection.

- [x] **Step 2: Run the lifecycle tests and confirm they fail**

Run: `pytest tests/test_ai_action_proposals.py -q`
Expected: FAIL because proposal service and handlers are not implemented.

- [x] **Step 3: Implement the handler registry and proposal lifecycle**

Register only explicit action types. Persist normalized payload and hash, lock rows during revise/cancel/confirm, reject stale versions, recheck owner and permission, and persist result with business data in the same transaction. Replay of `EXECUTED` returns the saved result without re-running the handler.

- [x] **Step 4: Add the generic proposal API routes**

Add create, revise, cancel, and confirm endpoints under `/ai/action-proposals`; confirmation is a user endpoint and is never exposed as an Agent tool.

- [x] **Step 5: Run the lifecycle tests and confirm they pass**

Run: `pytest tests/test_ai_action_proposals.py -q`
Expected: PASS, including no domain write before confirmation.

### Task 3: F-06 采购申请动作处理器与兼容接入

**Files:**
- Modify: `backend/app/modules/purchase_requests/service.py`
- Modify: `backend/app/modules/ai/action_handlers.py`
- Modify: `backend/app/modules/ai/purchase_draft_confirmations.py`
- Modify: `backend/app/modules/ai/drafts.py`
- Modify: `backend/app/modules/ai/controller.py`
- Test: `tests/test_ai_action_handlers.py` (create)
- Test: `tests/test_ai_purchase_draft_confirmations.py`

**Interfaces:**
- Add `commit: bool = True` to `update_request` and `submit_request`; `commit=False` flushes and returns the domain object without committing.
- Register `purchase_request.create_draft`, `purchase_request.update_draft`, and `purchase_request.submit` handlers.
- Existing purchase-draft endpoints remain adapters for new generic IDs and legacy pending IDs during the 10-minute expiry window.

- [x] **Step 1: Add failing purchase action tests**

Cover create preview without a business row, update diff and allowed fields, submit preflight blockers, current-version confirmation, stale request rejection, department/permission change rejection, old confirmation replay, and submit creating exactly one approval node.

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `pytest tests/test_ai_action_handlers.py tests/test_ai_purchase_draft_confirmations.py -q`
Expected: FAIL for the new generic action cases.

- [x] **Step 3: Add transaction-aware service options**

Refactor request update and submit to honor `commit=False` while preserving current default commit behavior for HTTP callers. Keep domain validation and audit creation in the domain service.

- [x] **Step 4: Implement create, update, preflight, and submit handlers**

Reuse current natural-language draft proposal and product/unit snapshots for create. For existing requests, snapshot the authorized request and lines; validate through the same rules used by domain services. Require no blockers before creating a submit proposal, then revalidate at confirm time.

- [x] **Step 5: Adapt existing purchase draft endpoints**

Write new previews to the generic ledger while retaining the existing response shape. Resolve current generic IDs first; fall back to the legacy confirmation table only for pending rows created before deployment.

- [x] **Step 6: Run the focused tests and confirm they pass**

Run: `pytest tests/test_ai_action_handlers.py tests/test_ai_purchase_draft_confirmations.py tests/test_ai_drafts.py -q`
Expected: PASS; legacy preview, current proposal, create, update, preflight, and submit paths are covered.

### Task 4: F-07 询价草稿动作处理器

**Files:**
- Modify: `backend/app/modules/rfqs/service.py`
- Modify: `backend/app/modules/ai/action_handlers.py`
- Test: `tests/test_ai_action_handlers.py`
- Test: `tests/test_procurement_state_machines.py` (existing; extend)

**Interfaces:**
- Add `commit: bool = True` to `create_rfq`; `commit=False` flushes and returns the new DRAFT without committing.
- Register `rfq.create_draft` with `procurement.rfqs.write` permission.
- Existing `supplier_quotes.compare` remains read-only and is not coupled to draft confirmation.

- [x] **Step 1: Add failing RFQ action tests**

Cover visible approved request, non-approved or out-of-scope source request, stale source lines, inactive supplier/product/unit, no write before confirmation, DRAFT after confirmation, replay with no duplicate RFQ, and compare tool remaining read-only.

- [x] **Step 2: Run RFQ action tests and confirm they fail**

Run: `pytest tests/test_ai_action_handlers.py -q -k rfq`
Expected: FAIL because the RFQ proposal handler is not registered.

- [x] **Step 3: Make RFQ creation transaction-aware**

Add `commit=False` support while preserving default HTTP behavior and existing scope/approval/reference validation.

- [x] **Step 4: Implement RFQ proposal and confirmation**

Snapshot the approved request and lines plus selected supplier, product, and unit references; revalidate all references before invoking `create_rfq(commit=False)`.

- [x] **Step 5: Run RFQ tests and confirm they pass**

Run: `pytest tests/test_ai_action_handlers.py tests/test_procurement_state_machines.py -q`
Expected: PASS.

### Task 5: Agent 意图契约、提示词与确定性摘要

**Files:**
- Modify: `backend/app/modules/ai/schema.py`
- Modify: `backend/app/modules/ai/routing.py`
- Modify: `backend/app/modules/ai/drafts.py`
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Test: `tests/test_ai_routing.py`
- Test: `tests/test_ai_drafts.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Structured understanding distinguishes read query, purchase request create/update/submit proposal, RFQ draft proposal, and clarification.
- Agent may call proposal preparation only; it cannot call confirm/cancel endpoints or infer confirmation from user intent.
- Deterministic response uses persisted proposal `diff`, `blockers`, and state.

- [x] **Step 1: Add representative failing intent samples**

Add samples for “创建采购申请草稿”, “修改申请用途”, “检查后提交申请”, “按已审批申请创建询价草稿”, and “比较报价但不要创建/发送”. Verify read/write intent separation and exact resource slots.

- [x] **Step 2: Run routing tests and confirm they fail**

Run: `pytest tests/test_ai_routing.py tests/test_ai_drafts.py -q`
Expected: FAIL for the new action categories and distinctions.

- [x] **Step 3: Update the existing prompt and Schema**

Extend the current structured understanding contract and purchase-draft prompt with action type, exact resource reference, candidate fields, and explicit clarification conditions. Preserve all existing read-only constraints; model output is candidate data only.

- [x] **Step 4: Add deterministic proposal summaries**

Render current action, target, field diff, warnings/blockers, expiry, and confirmation requirement from server results; never let a model produce confirmation success text.

- [x] **Step 5: Run representative routing and summary tests**

Run: `pytest tests/test_ai_routing.py tests/test_ai_drafts.py tests/test_agent_runtime.py -q`
Expected: PASS with existing read-only query samples unchanged.

### Task 6: 前端提案预览、确认和业务入口

**Files:**
- Modify: `frontend-design/apps/web-chemicalops/src/api/ai/agent.ts`
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/workspace/index.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/workspace/modules/page-copilot-drawer.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/procurement/purchase-requests/modules/detail.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/procurement/rfqs/modules/form.vue`
- Test: `frontend-design/apps/web-chemicalops/src/views/ai/workspace/action-proposal-policy.test.ts` (create)

**Interfaces:**
- API client exposes typed create/revise/cancel/confirm calls and response types for the generic proposal contract.
- Confirm action sends confirmation ID, exact preview version, and `confirm: true` only from a user click.
- Existing draft preview panel stays the shared visual template; action-specific fields and diffs are data/configuration.

- [x] **Step 1: Add failing front-end policy tests**

Test that only PENDING proposals with a current confirmation ID/version enable the confirm action; blockers and in-flight state disable it; stale version responses cannot overwrite a newer preview.

- [x] **Step 2: Run the focused front-end test and confirm it fails**

Run from `frontend-design/apps/web-chemicalops`: `pnpm exec vitest run src/views/ai/workspace/action-proposal-policy.test.ts`
Expected: FAIL because the policy module is not defined.

- [x] **Step 3: Add typed API calls and reusable proposal policy**

Implement typed endpoints and a small pure policy module for confirm eligibility and preview replacement.

- [x] **Step 4: Connect workspace and page entry points**

Render create/update/submit/RFQ proposals using existing preview/card and form/modal templates. Show explicit target, diff, evidence, warnings, blockers, and success result. Confirmation remains unavailable until the user presses the button.

- [x] **Step 5: Run focused front-end test and typecheck**

Run: `pnpm exec vitest run src/views/ai/workspace/action-proposal-policy.test.ts` and `pnpm typecheck` from `frontend-design/apps/web-chemicalops`.
Expected: PASS.

### Task 7: 文档回填与整体验收

**Files:**
- Modify: `docs/企业级Agent功能蓝图与业务AI打通方案.md`
- Modify: `docs/Agent功能专项排查报告.md`
- Verify: `tests/test_ai_action_proposals.py`
- Verify: `tests/test_ai_action_handlers.py`
- Verify: `tests/test_ai_drafts.py`
- Verify: `tests/test_ai_purchase_draft_confirmations.py`
- Verify: `tests/test_ai_routing.py`
- Verify: `tests/test_agent_runtime.py`
- Verify: `tests/test_procurement_state_machines.py`

- [x] **Step 1: Update F-05/F-06/F-07 status and evidence**

Record implemented boundaries and exact verification evidence. Do not modify STAR or README.

- [x] **Step 2: Run the focused backend regression set**

Run: `pytest tests/test_ai_action_proposals.py tests/test_ai_action_handlers.py tests/test_ai_drafts.py tests/test_ai_purchase_draft_confirmations.py tests/test_ai_routing.py tests/test_agent_runtime.py tests/test_procurement_state_machines.py -q`
Expected: PASS with no permission, scope, read-only, or transaction regressions.

- [ ] **Step 3: Verify migration, compile, and diff** — Python compilation and `git diff --check` passed; the local database migration ledger could not be read from this sandbox.

Run: `python -m py_compile backend/app/modules/ai/action_proposals.py backend/app/modules/ai/action_handlers.py backend/app/modules/purchase_requests/service.py backend/app/modules/rfqs/service.py` and `git diff --check`.
Expected: both commands exit 0. Browser acceptance remains deferred to the unified pass.
