# Agent Evidence to Proposal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry verified Agent or batch query context into a purchase request draft proposal, including clarification, persisted evidence, Inbox reads, and explicit confirmation.

**Architecture:** Resolve the latest relevant conversation message server-side and pin its Agent/batch reference in namespaced conversation state while clarification is pending. Re-query tools under current permissions; persist verified evidence in the existing action proposal and revalidate it through the existing confirmation lifecycle.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Vue 3, TypeScript, pytest, Vitest.

**Spec:** [design](../specs/2026-10-25-agent-evidence-to-proposal-design.md)

## Global Constraints

- Client supplies conversation reference, never trusted evidence snapshots.
- Do not infer user quantity, purpose, budget, or choose ambiguous product/quote candidates.
- All tools and proposal actions retain current permission, scope, version, idempotency, and domain-service checks.
- Reuse existing frontend templates; do not modify STAR or README.

## Review Focus

- Cross-user, stale, revoked, and cross-conversation references must not leak data (backend tests).
- Batch and Agent results must resolve by latest relevant message and remain pinned during follow-up (backend tests).
- Product changes clear unrelated evidence; missing requirements never mint a confirmable proposal (backend tests).
- Draft creation proposals remain visible in Inbox without an existing resource ID (backend tests).
- Old responses cannot overwrite a switched conversation; no-conversation draft flow remains compatible (frontend tests).

---

### Task 1: Server-side bridge context and clarification persistence

**Files:** `backend/app/modules/ai/drafts.py`, `backend/app/modules/ai/purchase_draft_bridge.py`, `backend/app/modules/ai/conversation_store.py`, `tests/test_ai_drafts.py`, `tests/test_ai_purchase_draft_bridge.py`.

- [x] Add failing tests for Agent and batch message resolution, pinned follow-up, expired clarification, and invalid ownership.
- [x] Run focused tests and observe expected failures.
- [x] Implement namespaced versioned `purchase_draft_bridge` state and server-side source resolution.
- [x] Re-query eligible tools under current user scope; reject ambiguous/stale sources.
- [x] Run focused tests.

### Task 2: Persist and revalidate proposal evidence

**Files:** `backend/app/modules/ai/drafts.py`, `backend/app/modules/ai/action_proposals.py`, `tests/test_ai_action_proposals.py`, `tests/test_ai_action_proposal_inbox.py`.

- [x] Add failing lifecycle tests for evidence persistence, source permission revocation, product replacement, pre-confirmation evidence change, and executed replay.
- [x] Run tests and observe expected failures.
- [x] Pass verified evidence only through service functions; public payload schemas stay strict.
- [x] Include create-draft proposals in Inbox with safe visibility absent a resource ID.
- [x] Revalidate sources before execution; guard proposal version/hash after validation.
- [x] Run focused regressions.

### Task 3: Workbench conversation continuity

**Files:** `frontend-design/apps/web-chemicalops/src/api/ai/index.ts`, `frontend-design/apps/web-chemicalops/src/views/ai/workspace/index.vue`, `frontend-design/apps/web-chemicalops/src/api/ai/draft-preview.test.ts`.

- [x] Add tests for conversation ID propagation and no-conversation compatibility.
- [ ] Run frontend tests and observe expected failures. (本机沙箱禁止 Vitest 子进程，未能执行；`vue-tsc` 通过。)
- [x] Pass active conversation ID for natural-language and structured follow-up previews; retain existing chat epoch guard.
- [ ] Run relevant Vitest and typecheck. (typecheck 通过；Vitest 待可运行环境补跑。)

### Task 4: Regression and documentation

**Files:** direct Agent runtime documentation and blueprint progress only.

- [x] Run backend focused regressions.
- [x] Update only verified status and known browser/model coverage.
- [ ] Run `git diff --check`; report browser acceptance only if executed. (浏览器验收未执行。)
