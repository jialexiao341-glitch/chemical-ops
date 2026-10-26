# 订单交期跟进实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在当前会话逐项执行；用户已要求开始落实，不重复请求执行授权。

**Goal:** 在订单详情准备、修订和确认保存有来源的交期催办草稿，并从本人 Inbox 回看。

**Architecture:** 订单领域读服务负责事实和草稿，`deliveries.followup_draft` 处理器接入既有提案版本/权限/幂等事务，前端复用 ActionProposalDetail 与 Modal。结果仅保存提案账本。

**Tech Stack:** FastAPI / SQLAlchemy / Pydantic、Vue / antdv-next、pytest / Vitest / vue-tsc。

**Spec:** [设计](../specs/2026-10-26-order-followup-design.md)

## Global Constraints

- 当前工作区已有用户授权的蓝图改动，保留原改动；本次不自动提交、推送或另建工作树。
- 复用现有业务弹窗、控件和提案详情样式。
- 服务端强制当前权限、订单范围、状态、事实快照与版本边界；不发送消息。
- 不新增依赖，不修改 README/STAR；浏览器验收统一收尾。

## Review Focus

- 明细收货变化而订单更新时间未变，仍须使旧预览失效。
- 缺交期/跨上海业务日，不伪造日期或沿用过期判断。
- 无读取权限或订单范围撤销，Inbox 隐藏正文与证据。
- 修改补充说明不可切换订单或覆盖来源事实。
- 重复确认仅返回原草稿，不产生外部发送或业务变更。

### Task 1: 事实草稿与动作处理器

**Files:** 新增 `backend/app/modules/purchase_orders/followup.py`、`tests/test_ai_delivery_followup.py`；修改 `backend/app/modules/ai/action_handlers.py`、`capabilities.py`。

**Interfaces:** `build_followup(db, user, order_id, *, note='', for_update=False) -> dict` 返回正文、事实快照与提示；处理器负责准备、重验和返回待保存结果。

- [x] 写非法输入、状态、来源/日期/数量、来源变化测试，运行并确认失败。
- [x] 实现领域草稿与处理器，使用已存在订单范围服务、business_today 和 format_decimal。
- [x] 注册业务页面能力，运行定向测试。

### Task 2: Inbox 与修订边界

**Files:** 修改 `backend/app/modules/ai/action_proposals.py`、`tests/test_ai_action_proposal_inbox.py`；新增测试复用现有 SQLite 提案夹具。

**Interfaces:** Inbox 复用订单来源入口，revision_values 仅暴露 `followup_note`；修订仅合并说明，不接受资源切换；确认沿用账本幂等。

- [x] 先写本人隔离、撤权隐藏、范围撤销、修订版本和重复确认测试，确认新增测试失败。
- [x] 接入提案读取和修订，验证新旧动作回归。

### Task 3: 订单入口与既有提案弹窗

**Files:** 修改 `frontend-design/apps/web-chemicalops/src/views/procurement/purchase-orders/detail.vue`、`src/views/ai/tasks/ActionProposalDetail.vue`；补针对性前端测试。

- [x] 写订单入口权限/状态、正文/来源和补充说明展示的测试，确认失败。
- [x] 原模板接入准备/读取/修订/取消/确认保存，不新增视觉模板；控制重复请求和失效预览。
- [x] 运行 Vitest 定向用例、应用类型检查及后端相关回归，记录环境跳过；检查 diff 和 UI 模板一致性。

## 执行记录

- Ruling: 首期保存草稿至通用账本，不新建发送渠道或业务表；保持人工对外发送边界。
- Ruling: 按当前订单主单与明细已收数生成跟进内容，不承诺已读取独立物流记录或供应商回复历史。
- 未授权提交 Git，计划中的验证完成后保留本地改动。

- Task 1: complete — 新领域/动作 22 项回归通过；非法参数、状态、逐行数量/日期/单位、来源变化均覆盖。
- Task 2: complete — 新增 Inbox 修订、版本、权限/范围与确认幂等测试；独立复核发现已执行确认重放缺少订单范围校验，先用失败回归复现，再集中修复两处幂等结果读取分支。复核已确认该问题闭合。
- Task 3: complete — 订单详情直接复用 ActionProposalDetail 与现有 Modal；准备失败后的刷新沿用同一幂等键。前端 5 文件 18 passed，应用 vue-tsc exit 0。
- 验证结果：后端 7 文件 94 passed、无跳过；前端 5 文件 18 passed；git diff --check 通过。没有进行 MySQL 并发或浏览器验收，也没有触发对外消息。
- 环境处理：Corepack 尝试下载 pnpm 时网络不可用，改用已安装 Vitest/vue-tsc 的 Node 入口；Vitest 系统临时目录重命名受限时改用工作区已忽略缓存目录。不新增或安装依赖。
- 样式复核：沿用订单工具栏 Button、任务中心 Modal 宽度及 ActionProposalDetail；仅替换业务字段和按钮文案，正文用换行展示，未新增视觉模板。
