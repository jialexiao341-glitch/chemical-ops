# Agent 同步数据库操作卸载实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项实施；步骤使用复选框跟踪。

**Goal:** Agent 运行期间的同步数据库操作不再阻塞应用事件循环，同时保持每个任务的数据库操作串行、权限重验和取消/超时语义。

**Architecture:** 在 Agent 异步图节点中将同步数据库/工具函数交给 `asyncio.to_thread`，并确保同一任务同一时刻只运行一个数据库操作。将模型调用结算回调改为可异步等待，使 token 预算的持久化也可卸载；数据库操作被取消时等待线程操作收尾后再处理终态，避免同一 Session 并发使用。

**Tech Stack:** Python asyncio、SQLAlchemy Session、pytest。

**Spec:** `docs/Agent功能专项排查报告.md` 的 AG-05。

## Global Constraints

- Agent 同步数据库调用不能占用主事件循环等待 SQL。
- 同一 `Session` 不得并发访问；线程中的数据库操作必须串行并在状态切换前收尾。
- 现有 RBAC、数据范围、任务 revision/fencing、只读工具和 token 预算不变。
- 不改变 API、持久化格式或数据库 schema。
- 不声称提升 P95；没有跑真实并发基准时明确标注未验证。

## Review Focus

- 同步工具调用延迟期间，事件循环仍能响应其他协程。
- 模型 token 结算仍在下一次业务动作前持久化，任务恢复预算不倒退。
- 超时/取消时数据库线程操作结束后才回滚/写最终状态，不发生 Session 并发。
- 权限撤回、重复工具、候选重验和数据库异常保持原错误码与轨迹。
- 同步 `settle` 的现有调用者与测试兼容；异步 Agent 调用采用 awaitable 结算。

---

### Task 1: 提供 awaitable token 预算结算

**Files:**
- Modify: `backend/app/modules/ai/gateway.py`
- Modify: `backend/app/modules/ai/llm.py`
- Test: `tests/test_llm_gateway.py`

- [x] 先覆盖 async settle callback 的等待、同步 settle 的既有兼容和预算超限。
- [x] 验证新增异步契约前测试失败。
- [x] 实现共享结算计算及 awaitable callback 支持，LLM async 请求 await 结算结果。
- [x] 重跑 Gateway/LLM 测试。

### Task 2: 串行卸载 Agent 数据库操作

**Files:**
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Test: `tests/test_agent_runtime.py`

- [x] 新增事件循环活性回归：模拟慢同步 Agent 工具时，heartbeat 仍持续运行；断言 DB 工具不在事件循环线程。
- [x] 将 plan/execute/persist/token-budget/final-read 中的同步 SQL 与只读工具调用改为串行线程卸载。
- [x] 取消/超时等待当前同步 DB 调用收尾后再回滚或持久化终态。
- [x] 验证事件循环活性、预算持久化、取消/超时与权限回归。

### Task 3: 完整验证与状态记录

- [x] 运行 Agent Runtime、队列、Gateway 与查询隔离回归。
- [x] 运行 `git diff --check`；不跑并发基准时明确记录验证边界。
