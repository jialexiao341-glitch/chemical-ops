# Agent 工具 SQL 真正中断实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 按任务实施；每个步骤使用复选框跟踪。遵循 TDD：先写失败测试，再实现，再运行对应回归。

**Goal:** 为只读 Agent 工具提供贯穿整个工具调用的 SQL 级超时，并在 MySQL 与 SQLite 中真正中断超时语句。

**Architecture:** 新建 AI 模块的超时上下文与方言中断适配层，在应用 SQLAlchemy Engine 的执行事件中应用剩余预算。`execute_tool` 建立工具预算，Agent Runtime 和多意图批处理提供父任务截止时间；统一异常映射为 `TOOL_TIMEOUT`，未知方言失败关闭。

**Tech Stack:** Python 3.12、asyncio、ContextVar、SQLAlchemy 2、PyMySQL、MySQL 8.0、sqlite3、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-agent-tool-sql-timeout-design.md`

## Global Constraints

- 新增配置 `agent_tool_timeout_seconds` 默认 15 秒，范围 1–60 秒。
- 工具预算是整次调用的绝对单调时钟截止时间，同一工具内多条 SQL 不重置预算。
- 首期支持 `mysql+pymysql` 与 SQLite；其他数据库方言返回 `TOOL_TIMEOUT_UNSUPPORTED`。
- MySQL SELECT 使用 `MAX_EXECUTION_TIME(n)`，剩余时间毫秒向上取整，亚毫秒时不发 SQL；SQLite 使用 progress handler，每 1,000 条虚拟机指令检查截止时间。
- 无工具超时上下文时，不改变普通业务 SQL 行为。
- 超时不自动重试；不记录 SQL 参数、用户查询或敏感数据。
- 线程数据库调用结束并退出 SQLAlchemy 栈后，才能释放或复用其 Session。
- 本阶段不做浏览器验收；按用户要求并入后续统一验收。
- 除非用户明确要求提交，本计划不提交 Git。

## Review Focus

- 绝对预算在同一工具多条 SQL 间是否正确递减；用顺序 SQLite 查询验证第二条查询只使用剩余时间。
- MySQL CTE、大小写、前置注释等语句形态能否安全识别主查询；无法识别时是否在执行前失败。
- SQLite 连接池复用是否残留 progress handler；分别验证成功、SQL 异常和超时路径。
- Agent 与批任务对超时的状态是否稳定；验证 Agent 停止重规划，批任务保留已完成项并继续独立项。
- 协程任务整体超时与 SQL 工具超时同时发生时，Session 是否只在 DB 调用栈收尾后操作。
- 批处理取消发生在 `asyncio.to_thread` 工作期间时，调用方是否先等待线程退出，再回滚或提交共用 Session。

---

### Task 1: 建立 SQL 超时上下文与数据库中断钩子

**Files:**
- Create: `backend/app/modules/ai/tool_sql_timeout.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/db.py`
- Test: `tests/test_agent_tool_sql_timeout.py`

**Interfaces:**
- `tool_sql_timeout.py` 提供 `ToolExecutionTimeout`, `ToolTimeoutUnsupported`, `tool_deadline_context(timeout_seconds: float, parent_deadline: float | None = None)`，以及 `current_tool_deadline() -> float | None`。
- 同模块提供 `agent_task_deadline_context(timeout_seconds: float)` 和 `current_task_deadline() -> float | None`；工具截止时间取工具截止时间与父任务截止时间中更早者。
- 同模块提供 SQLAlchemy Engine 事件处理器安装函数 `install_tool_sql_timeout_listeners(engine) -> None`，供生产 Engine 和测试 Engine 显式安装。
- `core/db.py` 对应用 Engine 安装事件；事件仅在 `current_tool_deadline()` 有值时工作。

- [x] **Step 1: 编写 SQLite 中断与无上下文隔离测试**

在 `tests/test_agent_tool_sql_timeout.py` 建立独立 SQLite Engine 并安装监听器，新增 `test_sqlite_tool_deadline_interrupts_long_query`（长查询抛 `ToolExecutionTimeout`）、`test_sqlite_short_query_completes_with_tool_deadline`（短查询成功）和 `test_expired_deadline_rejects_before_cursor_execute`（断言 cursor 未收到 SQL）。

- [x] **Step 2: 运行目标测试确认失败**

运行：`cd backend; python -m pytest ../tests/test_agent_tool_sql_timeout.py -q`

预期：因超时模块或监听器尚不存在而失败。

- [x] **Step 3: 新增配置和截止时间上下文**

在 `Settings` 增加 `agent_tool_timeout_seconds: int = Field(default=15, ge=1, le=60)`。在 `tool_sql_timeout.py` 以 `time.monotonic()` 建立绝对截止时间，并将其与可选父截止时间取最早值；ContextVar token 在上下文退出时恢复。

- [x] **Step 4: 添加 SQLAlchemy 方言事件处理**

在 `before_cursor_execute` 中检查方言并读取剩余预算。SQLite 通过 `sqlite3.Connection.set_progress_handler(callback, 1000)` 中断执行，在 `after_cursor_execute` 和 `handle_error` 两条退出路径清除回调。MySQL 识别安全的只读 SELECT / WITH 查询并注入 `MAX_EXECUTION_TIME`；无法安全定位主查询或遇到其他方言时，在执行 SQL 前抛出对应超时异常。仅在工具截止时间已到时将 DBAPI 中断映射为 `ToolExecutionTimeout`。

- [x] **Step 5: 扩充边界测试并运行目标测试**

添加 `test_queries_without_tool_context_are_unchanged`、`test_mysql_hint_is_inserted_after_main_select_for_select_and_cte`、`test_submillisecond_budget_rejects_before_execute`、`test_unsupported_dialect_fails_closed` 和 `test_sqlite_progress_handler_cleared_after_success_error_and_timeout`；分别断言无上下文 SQL 不变、普通 SELECT / WITH 提示插入主查询 SELECT 后、亚毫秒预算不执行、未知方言在执行前报错、SQLite 连接复用不遗留 handler。

运行：`cd backend; python -m pytest ../tests/test_agent_tool_sql_timeout.py -q`

预期：全部通过。MySQL 真实服务端中断留到 MySQL 8.0 集成环境确认。

### Task 2: 将工具预算接入 Agent Runtime 与多意图批处理

**Files:**
- Modify: `backend/app/modules/ai/agent_tools.py`
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Modify: `backend/app/modules/ai/multi_intent.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_ai_multi_intent.py`
- Test: `tests/test_agent_read_tools.py`

**Interfaces:**
- `agent_tools.execute_tool` 在入口处进入 `tool_deadline_context(get_settings().agent_tool_timeout_seconds, parent_deadline=current_task_deadline())`；该预算覆盖权限检查、参数校验、handler 和输出 Schema 校验。
- `agent_runtime` 与 `multi_intent` 在整次任务范围建立父截止时间上下文，使 `asyncio.to_thread` 中的 `execute_tool` 继承剩余预算。
- `ToolExecutionTimeout` 与 `ToolTimeoutUnsupported` 是可区分的专用异常，分别映射到 `TOOL_TIMEOUT` 与 `TOOL_TIMEOUT_UNSUPPORTED`。

- [x] **Step 1: 编写 Agent 超时状态测试**

新增 `test_tool_timeout_fails_task_without_replanning`，断言工具轨迹写入 `TOOL_TIMEOUT`、任务 FAILED 且 Planner 只调用一次；新增 `test_invalid_tool_arguments_keep_existing_error_mapping`，断言参数错误仍走 `INVALID_TOOL_REQUEST`。

- [x] **Step 2: 运行目标测试确认失败**

运行：`cd backend; python -m pytest ../tests/test_agent_runtime.py -k "tool_timeout" -q`

预期：新行为测试因未识别专用超时异常而失败。

- [x] **Step 3: 在统一工具入口建立预算**

在 `agent_tools.execute_tool` 入口设置工具上下文并覆盖整个调用；保留现有权限、输入 Schema、输出 Schema 与只读校验。

- [x] **Step 4: 将任务截止时间与错误语义接入 Agent Runtime**

在 `_drive_impl` 的整体任务时限中建立父截止时间上下文；工具执行节点捕获专用超时异常，给当前工具轨迹写入 `TOOL_TIMEOUT` 或 `TOOL_TIMEOUT_UNSUPPORTED` 后向任务层传播；任务层以相同错误码终止本轮任务，不交回规划器重试。工具轨迹随失败终态持久化。维持 `_offload_db_call` 等待工作线程结束后才做回滚和终态持久化的行为。

- [x] **Step 5: 编写并意图批处理的超时与独立项测试**

新增 `test_product_tool_uses_remaining_batch_deadline`、`test_tool_timeout_keeps_completed_results_and_runs_independent_items` 与 `test_batch_deadline_keeps_task_timeout_code`，断言父截止时间递减传入工具、超时项之外的已完成与独立项结果保留、整体截止仍映射 `TASK_TIMEOUT`。

- [x] **Step 6: 映射批任务超时并运行目标测试**

在 `multi_intent.run_items` 单项异常处理中，优先识别专用超时异常并记录对应错误码；将产品任务的 `asyncio.to_thread` 包进取消安全的同步卸载 helper，取消时 shield 工作线程并等待其退出后再回滚/提交共用 Session，沿用现有逐项提交和独立项执行次序。新增 `test_batch_cancellation_waits_for_tool_thread_before_session_cleanup`，使用事件同步线程完成与 Session rollback，断言线程结束先于清理。运行：

```powershell
cd backend
python -m pytest ../tests/test_agent_runtime.py ../tests/test_ai_multi_intent.py ../tests/test_agent_read_tools.py -q
```

预期：目标测试全部通过，权限、参数、只读和既有整体取消行为保持原结果。

### Task 3: 指标、完整回归与集成边界记录

**Files:**
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Modify: `backend/app/modules/ai/multi_intent.py`
- Modify: `docs/Agent功能专项排查报告.md`
- Test: `tests/test_agent_tool_sql_timeout.py`
- Test: `tests/test_agent_runtime.py`
- Test: `tests/test_ai_multi_intent.py`

**Interfaces:**
- 超时观测沿用现有工具耗时指标，并新增低基数计数器，标签仅限工具名、数据库方言和结果类别。
- 专项排查报告只更新 AG-08 对应进度与证据，不更新项目 STAR 文档或 README。

- [x] **Step 1: 编写超时指标与脱敏轨迹断言**

断言超时计数和工具轨迹具有工具名、方言、耗时及错误码；查询参数、租户 ID 和 SQL 不进入指标标签或用户可见回复。

- [x] **Step 2: 添加观测并运行相关回归**

实现超时计数和错误码记录，运行 SQLite 中断、Agent Runtime、多意图批处理及只读工具测试。

- [x] **Step 3: 运行 Agent 全面回归**

运行：`cd backend; python -m pytest ../tests/test_agent_runtime.py ../tests/test_agent_queue_runtime.py ../tests/test_agent_read_tools.py ../tests/test_agent_rfq_continuation.py ../tests/test_ai_multi_intent.py ../tests/test_ai_query_isolation.py ../tests/test_ai_candidate_resolution.py ../tests/test_ai_capability_manifest.py ../tests/test_agent_tool_sql_timeout.py -q`

预期：全部通过。若已有冻结评测清单完整性测试的历史失败，单独报告，不将其当成本功能通过证据。

- [x] **Step 4: 执行静态检查并记录 MySQL 集成验收边界**

运行：`git diff --check` 与 `python -m compileall backend/app/modules/ai/tool_sql_timeout.py backend/app/modules/ai/agent_tools.py backend/app/modules/ai/agent_runtime.py backend/app/modules/ai/multi_intent.py backend/app/core/db.py backend/app/core/config.py`。

确认是否存在可用 MySQL 8.0 集成环境；若没有，在专项排查报告中明确标记服务端中断行为待统一验收，不以 SQL 字符串模拟结果代替。

- [x] **Step 5: 汇总变更与验证结果**

列出已实现的超时路径、实际执行的检查、未执行的浏览器验收及 MySQL 集成验收边界。除非用户再次要求提交，不创建 Git 提交。
