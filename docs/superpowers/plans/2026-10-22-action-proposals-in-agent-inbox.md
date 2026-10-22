# Agent Inbox 动作提案汇总实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在 Agent Inbox 汇总当前用户动作提案，支持查看预览、沿用既有确认接口处理，并识别提案失效原因和原单据入口。

**Architecture:** 后端为本人提案增加列表与详情只读接口，在读取时派生有效性和可用性，不返回 payload 或资源快照。前端扩展现有 AI 任务列表页，加入提案列表和详情 Modal，复用既有动作接口与页面组件风格。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy；Vue 3、TypeScript、antdv-next、VXE Grid。

**Spec:** `docs/superpowers/specs/2026-10-22-action-proposals-in-agent-inbox.md`

## Global Constraints

- 只返回当前用户自己的提案；读取路由保留 `ai.workspace.read` 权限。
- 不向前端返回提案 `payload`、资源快照、权限码或幂等键。
- 确认、修订和取消继续使用现有动作提案接口及 `preview_version`。
- 复用 Agent Inbox 现有 VXE Grid、Modal、按钮和项目样式，不新建视觉模板。
- 不自动修改 STAR 文档或 README；不提交代码。
- 按本次任务的执行要求，不新增或运行测试；完成适合本次修改的类型检查和构建验证，并如实报告。

## Review Focus

- 其他用户的提案编号不能读取或列出：后端路由的每个查询都限定 `user_id`。
- 用户失去写权限后提案仍可读但不可操作：响应区分 `availability=PERMISSION_REVOKED`，所有写操作仍由原接口复核。
- 资源不可见时不泄露编号、证据或路由：详情组装器清除关联资源入口和敏感单号。
- 询价草稿没有已创建询价单：跳转来源采购申请；新建采购申请提案不伪造目标单据链接。
- 资源快照验证遇到预期业务异常时仍能正常读取列表：将其显示为不可用/失效状态，并保证 SQLAlchemy Session 可继续响应。

---

### Task 1: 后端提案状态与读取契约

**Files:**
- Modify: `backend/app/modules/ai/schema.py`
- Modify: `backend/app/modules/ai/action_handlers.py`
- Modify: `backend/app/modules/ai/action_proposals.py`
- Modify: `backend/app/modules/ai/controller.py`

**Interfaces:**
- Produces: `list_action_proposals(db, user, *, page: int, page_size: int, inbox_only: bool) -> AIActionProposalPage`
- Produces: `get_action_proposal(db, user, confirmation_id: str) -> AIActionProposalRead`
- `AIActionProposalRead` 在当前预览字段上增加 `created_at`、`business_reference`、`source_route`、`availability`；`availability` 为 `AVAILABLE | PERMISSION_REVOKED | RESOURCE_UNAVAILABLE`。
- `AIActionProposalRead.revision_values` 仅返回安全可编辑字段：申请修改提供用途/优先级/预算/币种/期望日期；询价草稿提供报价截止/期望交付日期/交付要求。
- 分页响应结构沿用项目 `{items, total}` 契约，列表项和详情返回相同的安全展示字段。

- [x] `inbox_only=true` 包含 `PENDING`、`EXPIRED` 和 `INVALIDATED`，使用户可在 Inbox 识别需要重建的提案；完整列表包含所有状态，并按创建时间倒序分页。
- [x] 从 action handler 按类型读取当前领域资源，重用其当前状态/快照校验；将已过期记录规范为 `EXPIRED`，资源快照不一致规范为 `INVALIDATED`。
- [x] 读取路径校验资源时不加行锁；现有确认路径默认继续使用 `FOR UPDATE`。
- [x] Inbox 汇总仅纳入 `purchase_request.update_draft`、`purchase_request.submit` 和 `rfq.create_draft`。
- [x] 检查提案 `permission_code`，派生 `availability`；资源不可见时移除业务编号和路由，不能暴露敏感证据内容。
- [x] 对采购申请修改/提交构建采购申请路由；对 `rfq.create_draft` 从来源申请证据构建采购申请路由；新建采购申请不构造原单据路由。
- [x] 在 controller 新增 `GET /action-proposals` 和 `GET /action-proposals/{confirmation_id}`，保留路由级 AI 读取权限与所有者隔离。
- [x] 核对响应没有 `payload`、`expected_resource_snapshot`、`permission_code`、`idempotency_key`，并确认读取不会执行领域写入。
- [x] 运行后端适用的静态检查/导入检查；不添加或运行测试。

### Task 2: 前端读取 API 与提案详情组件

**Files:**
- Modify: `frontend-design/apps/web-chemicalops/src/api/ai/index.ts`
- Create: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/ActionProposalDetail.vue`

**Interfaces:**
- Consumes: Task 1 的 `AIActionProposalRead` 与分页 `{items,total}`。
- Produces: `getActionProposalPageApi(page, pageSize, inboxOnly)`、`getActionProposalApi(confirmationId)`。
- `ActionProposalRead.revision_values` 仅含服务端 allowlist 的可编辑字段，不包含执行 payload。
- 详情组件 props 为安全提案读取对象，emit `confirm`、`revise`、`cancel` 操作请求；不持有独立 API 或授权逻辑。

- [x] 在 `AiApi` 声明提案展示字段和 `availability` 联合类型，并实现列表/详情读取封装。
- [x] 详情组件展示差异、证据、警告、阻塞项、风险级别、过期时间和失效原因。
- [x] 只有 `status=PENDING`、`availability=AVAILABLE`、`requires_user_confirmation=true` 且无阻塞项时展示确认、修改、取消入口。
- [x] 将原单据入口渲染为 RouterLink；后端不提供路由时不显示入口。
- [x] 复用已存在的 antdv-next 控件与语义结构，不增加新 CSS 视觉系统。
- [x] 运行前端 TypeScript 检查；不添加或运行测试。

### Task 3: Agent Inbox 汇总与处理

**Files:**
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/index.vue`
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/ActionProposalDetail.vue`

**Interfaces:**
- Consumes: Task 2 列表/详情 API、Task 1 的可用性字段，以及现有 `reviseActionProposalApi`、`cancelActionProposalApi`、`confirmActionProposalApi`。
- 页面以当前 Agent Inbox/全部任务切换为基础；提案使用独立 grid 或同一页签列表，所有写操作必须提交当前预览版本。

- [x] 在 Agent Inbox 增加待确认提案入口/列表，展示提案动作类型、业务单号、状态和过期时间；全部任务模式仍可查看完整任务与提案记录。
- [x] 增加“查看”操作，在既有 Modal 模板中加载最新详情，显示读取中、读取失败和刷新后的状态。
- [x] 确认操作调用现有 confirm API；修改操作沿用 action type 对应输入字段并调用现有 revise API，展示新版本预览后再允许确认。
- [x] revise API 接受同一 PATCH 接口上的字段增量：申请修改只允许合并 `changes` 字段；询价草稿只允许合并三个安全表头字段，服务端保留其余执行 payload。
- [x] 取消操作调用现有 cancel API；确认、修改、取消成功或失败后刷新列表和详情，避免旧版本继续操作。
- [x] 对 `EXPIRED`、`INVALIDATED`、`PERMISSION_REVOKED`、`RESOURCE_UNAVAILABLE` 给出清楚状态文字并隐藏写操作。
- [x] 按项目要求复用列表模板、按钮、Modal 和操作菜单样式；确认列表宽度、滚动和窄屏布局。
- [x] 运行前端 lint/typecheck/build 中适用的非测试验证；未进行浏览器验收时明确标注。

### Task 4: 联调核对与交付

**Files:**
- Review: 上述后端和前端文件

- [x] 对照规格核对三类提案的单号、来源路由、状态、过期和权限显示映射。
- [x] 检查失效提案的确认、修订和取消控件都不可用，服务端原写接口仍执行最终复核。
- [x] 检查列表/详情的跨用户所有权限制，以及不可见资源的单号、证据、路由脱敏。
- [x] 完成前后端适用的构建/类型检查；记录命令和结果，不运行测试。
- [x] 对照现有 AI 任务列表模板进行 UI 复核；若未做浏览器验收，在交付说明中注明。

## UI Review Notes

- Reused the existing AI tasks VXE Grid and Modal patterns; surfaces use the project's `bg-card`, `border-border`, `text-muted-foreground`, and `text-primary` tokens.
- The detail layout uses the existing spacing scale (`space-y-4`, `p-3`, `gap-2`) and collapses metadata to one column below the small breakpoint.
- Status, availability, warning, blocker, loading, and disabled states are represented; form controls have accessible labels and semantic status/alert roles.
- Browser acceptance was not performed; the interaction and responsive layout were reviewed from the implementation and the production build.
