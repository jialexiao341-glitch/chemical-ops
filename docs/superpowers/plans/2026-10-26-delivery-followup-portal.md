# 交期催办门户闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将已保存催办草稿送达供应商门户，支持一次正式回复和可选交期更新。

**Architecture:** 采购订单领域保存独立催办记录，来源提案唯一；发送和回复调用现有权限、订单、通知和审计服务。供应商现有交期更新服务增加兼容的事务参数，两端复用现有弹窗与表格。

**Tech Stack:** FastAPI、SQLAlchemy、MySQL、Pydantic、Vue、TypeScript、antdv-next、pytest、Vitest。

**Spec:** `docs/superpowers/specs/2026-10-26-delivery-followup-portal-design.md`

## Global Constraints

- 保留保存草稿与发送两个动作，不新增外部发送渠道。
- 复用现有模板；不修改用户已有的采购订单报价加载改动，不自动提交。
- UTC 时间与上海业务日期；列表分页上限 100；回复说明上限 1000 字。
- 供应商只读取当前有效绑定的订单及同一供应商催办；服务端强制权限、状态、版本、确认与幂等。
- 浏览器验收按蓝图留到功能开发结束统一执行；本轮明确测试限制。

## Review Focus

- 保存草稿不会发送，来源提案与正文必须由服务器复核（Task 1）。
- 发送/回复撤权后的幂等重放不能泄漏记录（Task 1）。
- 交期更新后其他行写入失败时整笔回滚（Task 2）。
- 通知不携带敏感事实，点击后再次鉴权（Task 3）。
- 页面刷新、重复点击及请求失败不能复用过期可执行状态（Task 3）。

### Task 1: 催办领域与发送

**Files:** Create `backend/app/modules/purchase_orders/followup_model.py`, `followup_schema.py`, `followup_service.py`, `database/migrations/059_delivery_followups.sql`, `tests/test_delivery_followup_portal.py`; modify `purchase_orders/controller.py`.

**Interfaces:** `send_followup(db,user,order_id,data)->FollowupRead`; `list_followups(db,user,order_id,*,supplier=False,page=1,page_size=20)->FollowupPage`。发送输入为 confirmation_id、preview_version、confirm=true；记录唯一来源提案。

- [x] 写 SQLite 隔离测试：成功发送、通知接收范围、重复发送、事实变化、伪造提案、无接收人、撤权和跨订单拒绝；运行并观察缺少模块失败。
- [x] 实现迁移、模型、输入输出契约、分页和发送；先鉴权再查幂等，订单锁串行发送，通知和审计同事务。
- [x] 运行新测试与原 `test_ai_delivery_followup.py`；要求通过且保存草稿仍不发送。

### Task 2: 供应商回复与交期原子更新

**Files:** modify `followup_service.py`, `followup_schema.py`, `supplier_portal/controller.py`, `supplier_portal/service.py`; extend `test_delivery_followup_portal.py`。

**Interfaces:** `reply_followup(db,user,order_id,followup_id,data)->FollowupRead`；回复包含 request_key、message、可选 expected_date。`update_expected_delivery(...,commit=True)` 保持原调用兼容。

- [x] 先写回复成功、无日期、带日期、幂等重放、冲突、跨供应商、终态与无待收数量、业务日期、失败回滚测试并运行失败。
- [x] 实现锁顺序为订单→催办；同一记录只能回复一次；交期更新使用 `commit=False`，回复、历史、通知及审计同事务。
- [x] 执行发送/回复全套隔离回归及现有供应商服务相关可离线测试；数据库环境限制单独报告。

### Task 3: 两端入口与通知跳转

**Files:** Create `frontend-design/apps/web-chemicalops/src/api/delivery-followups.ts`, `src/views/procurement/purchase-orders/modules/followup-history.vue`; modify `src/api/index.ts`, `purchase-orders/detail.vue`, `supplier-portal/delivery-updates/index.vue`, `notification/index.vue`; add targeted frontend tests。

**Interfaces:** typed API for send/list/reply; history component receives orderId and supplierMode, emits changed after reply. Staff send uses executed proposal and explicit Modal.confirm; supplier reply uses existing DatePicker/Input.TextArea styles。

- [x] 添加发送确认、重复点击和通知目标权限的失败测试。
- [x] 订单详情接入保存后发送及历史；供应商交期页接入历史与回复；通知解析服务端授权记录引用后导航，不把 URL 参数当业务事实。
- [x] 执行 Vitest 定向测试与前端类型检查；核对复用模板、加载/禁用/失败/空状态，无新 CSS 视觉模板。

### Task 4: 总体验证与审查

- [x] 对比设计逐项核对；运行后端新增测试、草稿与动作权限回归、全仓收集检查、前端定向检查、`git diff --check`。
- [x] 独立 reviewer 审查当前差异（明确排除用户已有修改），修正重大问题并重跑相关测试。
- [x] 更新执行记录，交付代码范围、实测结果、环境限制；不自动提交或推送。

## Execution ledger

- 用户已明确要求“动代码吧”，本会话直接实施，不再增加计划审批回合。
- Ruling: 复用当前工作区，保留用户已存在的 crud.py 及报价加载测试；不切换分支或复制未提交内容。
- Pre-flight: Task 1 的 Schema/服务被 Task 2 和 Task 3 消费；统一使用 snake_case API 字段、同一供应商订单 URL；通知用催办记录 ID，经授权解析订单。

## 实施与验证记录

- Task 1 / 2 / 3 已实现；后端隔离回归覆盖草稿与发送分离、来源重验、权限、幂等、通知失败回滚及交期服务 commit=False。
- Review finding P2：MySQL RR 下普通查询可能读不到并发发送结果；已通过当前读、唯一冲突回滚后重新鉴权恢复处理，旧快照模拟已观察失败后通过。明细也在主单加锁后使用当前读刷新。
- 独立复核未发现其他可操作问题。真实 MySQL 并发测试已增加，但缺少 FOLLOWUP_TEST_MYSQL_URL，本轮跳过，未计作通过；未应用迁移、未执行统一浏览器验收。
- Ruling: 同步蓝图中直接失效的“催办发送/回复待开发”描述，补运行说明；未修改 README、STAR 或用户原有采购订单改动。
- 最终验证：后端定向 99 passed、1 skipped（真实 MySQL 并发）；前端 Vitest 9 passed；vue-tsc 退出码 0；全仓 1488 tests collected；Python 语法及 git diff --check 通过。
- 模板复核：历史和回复共用现有 Modal/Table/DatePicker/Input.TextArea 组件与 space-y-4、py-2 等业务弹窗排版；未增加样式表或独立控件视觉；加载、禁用、失败、空记录和权限状态已检查。此项为代码一致性复核，非浏览器视觉验收。
