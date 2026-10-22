# Agent 任务中心操作入口实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项实施；步骤使用复选框跟踪。

**Goal:** 让用户从任务中心按任务状态继续、取消、重试本人 Agent 只读任务。

**Architecture:** 保持后端 API 与状态机作为权威。前端在现有任务表行菜单和详情 Modal 中提供状态化操作；继续复用版本号与已保存候选，取消前确认，重试通过原始查询创建新任务并明确展示新任务编号。

**Tech Stack:** Vue 3、TypeScript、Ant Design Vue Next、Vben Vxe Grid、Vitest。

**Spec:** `docs/superpowers/specs/2026-10-22-agent-task-center-actions-design.md`

## Global Constraints

- 保持 Agent 只读；动作只能调用现有 API。
- 继续任务必须发送当前 `revision`，候选只能选择当前任务已有候选。
- 取消只对 `RUNNING` 开放；继续只对 `WAITING_INPUT` 开放；重试只对 `FAILED` 开放。
- 重试通过 `createAgentTaskApi` 创建新任务，只提交原始查询，不复制证据、候选或已执行工具结果。
- 复用 `tasks/index.vue`、`AgentChatTask` 和现有列表/弹窗模板。

## Review Focus

- 任务在 Modal 打开后状态已变化：后端拒绝过期 revision，界面刷新权威状态。
- 失败任务有多轮补充：重试只复制 `messages[0]`，不把后续选择/回复当作原始目标。
- 取消请求失败或任务已完成：界面不乐观覆盖服务端状态。
- 任务继续返回 202：界面显示 RUNNING 并通过任务刷新看到最终状态。
- 重复点击同一行操作：请求期间禁用该行操作，避免重复创建/续跑。

---

### Task 1: 提取并测试任务中心操作策略

**Files:**
- Create: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/task-actions.ts`
- Create: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/task-actions.test.ts`

**Interfaces:**
- Produces: `taskActions(status: AgentApi.Task['status']): Array<'view' | 'export' | 'continue' | 'cancel' | 'retry'>`。
- Produces: `retryQuestion(task: AgentApi.Task): string | undefined`，仅取 `messages[0]`，空输入返回 `undefined`。

- [x] **Step 1: 写失败测试**，覆盖五种状态操作矩阵、多轮 FAILED 任务只取首条原始查询，以及空查询不允许重试。
- [x] **Step 2: 运行新测试确认失败**：本地 Vitest 首先因模块不存在而失败；pnpm 经 Corepack 需联网下载，改用仓库本地 Vitest 与单 worker 参数。
- [x] **Step 3: 实现纯策略函数**，不在策略层处理网络调用或 UI。
- [x] **Step 4: 重跑测试确认通过**，并补充取消响应状态反馈断言。

### Task 2: 接入任务行菜单、详情操作与 API 状态刷新

**Files:**
- Modify: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/index.vue`
- Reuse: `frontend-design/apps/web-chemicalops/src/views/ai/workspace/agent-chat-task.vue`
- Reuse: `frontend-design/apps/web-chemicalops/src/api/ai/agent.ts`

**Interfaces:**
- Reuse API: `continueAgentTaskApi(id, data)`, `cancelAgentTaskApi(id)`, `createAgentTaskApi(question)`, `getAgentTaskApi(id)`。
- `AgentChatTask` 的 `continue` 事件已携带 revision 和候选选择；任务中心父组件负责提交并刷新。

- [x] **Step 1: 在操作策略测试中核验** `WAITING_INPUT` 仅提供继续、`RUNNING` 仅提供取消、`FAILED` 仅提供重试；终态无继续/取消/重试。
- [x] **Step 2: 运行新增取消竞态回归测试确认失败**，再实现反馈映射并观察测试通过。
- [x] **Step 3: 在任务中心根据 `taskActions` 生成行菜单；取消使用现有确认 Modal；重试调用 `createAgentTaskApi(retryQuestion(task))` 并提示新任务编号。**
- [x] **Step 4: 详情 Modal 展示候选选择及补充输入；提交携带当前 revision。继续和取消使用服务端返回值更新详情并刷新列表；请求中禁用重复操作，失败时显示中文提示并重新读取任务状态。**
- [x] **Step 5: 操作矩阵、原始查询提取和取消竞态均有边界测试；成功/失败响应路径通过代码复核。**
- [x] **Step 6: 本地 Vitest 20/20；`vue-tsc --noEmit --skipLibCheck` 退出码 0。pnpm 因 Corepack 下载受网络限制，改用仓库本地执行文件。**

### Task 3: 对照现有模板复核与交付检查

**Files:**
- Review: `frontend-design/apps/web-chemicalops/src/views/ai/tasks/index.vue`
- Review: `frontend-design/apps/web-chemicalops/src/views/ai/workspace/agent-chat-task.vue`

- [x] **Step 1: 对照任务中心现有表格、菜单、Modal 和 Agent 任务卡检查布局、状态文案与重复操作反馈。**沿用原页面样式与任务卡组件。
- [x] **Step 2: 检查 Git diff，确认未自动更新 STAR/README、无未授权提交，操作按 task id 关联。**
- [x] **Step 3: 本次未进行浏览器验收；交付时明确说明。**
