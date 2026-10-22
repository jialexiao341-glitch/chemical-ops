# Agent 工具 SQL 真正中断设计

## 状态

已批准，实施中。本文记录 AG-08 工具治理元数据之后的 SQL 超时实现方案。方案采用 SQLAlchemy 执行事件与工具级绝对截止时间。

## 背景

Agent 整体任务已有超时，但当前同步 SQL 通过 `asyncio.to_thread` 执行。取消协程不能停止工作线程中的数据库语句，运行时只能等待线程结束后安全归还请求 Session。因此，单纯缩短协程等待时间无法保证 SQL 被中断，也无法安全复用该 Session。

部署环境使用 MySQL 8.0 / PyMySQL，测试和本地环境使用 SQLite。Agent 工具目前是只读查询，工具调用可能包含一个或多个 SQL 语句。超时预算必须覆盖一次工具调用里的全部查询，而不能在每条 SQL 开始时重新计时。

## 目标

- 在工具级时限到达时，由数据库驱动/数据库执行层中断当前 SQL。
- 同一个工具调用中的多个 SQL 共用同一单调时钟截止时间。
- Agent 与多意图批量查询都以稳定的 `TOOL_TIMEOUT` 语义呈现超时，不把它误报为参数错误或普通查询失败。
- 超时后等待 SQLAlchemy 调用栈收尾，再允许请求 Session 被后续代码使用。
- 对未实现中断能力的数据库方言快速失败，避免无界 SQL 被误认为受超时保护。
- 不自动重试超时查询，不扩大现有只读工具的权限边界。

## 非目标

- 不改变 Agent 整体任务超时、路由或模型调用超时策略。
- 不增加数据库写入工具，不做进程隔离或任务队列改造。
- 不对非 Agent 的普通业务 SQL 全局加时限。
- 不承诺精确到毫秒的终止时间；SQLAlchemy、驱动和数据库仍有中断传播与清理开销。
- 不在本阶段做浏览器验收；依照项目约定并入后续统一验收。

## 采用的架构

### 1. 工具级截止时间上下文

在 Agent / 批量查询调用 `agent_tools.execute_tool` 的入口处创建单调时钟绝对截止时间，并通过 `ContextVar` 传入同步工具处理器及 SQLAlchemy 执行事件。`asyncio.to_thread` 会复制当前上下文，因此现有线程池调用链可以读取该值。

截止时间在整个工具调用中保持不变。每次执行 SQL 时计算剩余毫秒数：

```text
remaining_ms = ceil((deadline_monotonic - now_monotonic) * 1000)
```

若剩余时间小于等于零，执行事件在向数据库发送语句前直接抛出 `ToolExecutionTimeout`。有效截止时间取工具预算和 Agent 任务剩余时间的较早值，整体任务超时规则继续由现有 runtime 负责。

工具预算使用新增配置 `agent_tool_timeout_seconds`，默认 15 秒，范围 1–60 秒。该值是整次工具调用的预算，覆盖工具处理器准备与该处理器发起的所有 SQL。若后续工具需要不同预算，可在 ToolSpec 中加入可选覆盖值；首期不为每个工具设置独立数字，减少没有评测依据的差异。

### 2. MySQL 8.0 / PyMySQL 中断

在 SQLAlchemy `before_cursor_execute` 事件中，为 `SELECT` 语句插入由剩余预算计算出的 MySQL 优化器提示 `/*+ MAX_EXECUTION_TIME(n) */`。`n` 只来自服务端配置和单调时钟计算，不包含用户输入。该提示由 MySQL 服务端限制当前只读 SELECT 的执行时间；数据库达到限制后返回中断错误，PyMySQL 将其交给 SQLAlchemy。

SQL 识别必须覆盖普通 SELECT 和以 `WITH` 开始的查询。实现应仅在确认语句是只读查询且能安全定位主查询 SELECT 时注入提示；遇到未识别语句形态，不得猜测拼接。Agent 工具保持只读约束，任何非 SELECT 语句都不应借此绕过原有安全校验。

MySQL 端的 `MAX_EXECUTION_TIME` 是服务端语句中断机制，具体行为以 [MySQL 8.0 优化器提示文档](https://dev.mysql.com/doc/refman/8.0/en/optimizer-hints.html) 为准。预算毫秒数向上取整，允许最多约 1ms 的粒度误差，避免服务端提示在绝对截止时间前触发；小于 1ms 的剩余预算应在发 SQL 前超时。

### 3. SQLite 开发与测试中断

对 SQLite 连接，在语句执行前注册 `sqlite3.Connection.set_progress_handler`，回调检查同一个绝对截止时间，超时时返回非零值以中断 SQLite 虚拟机执行。回调的检查间隔使用固定的小批指令间隔（建议 1,000 条）控制开销与中断延迟。

无论 SQL 正常完成还是抛出异常，都要清除 progress handler，避免连接池复用连接时遗留前一次工具的截止时间。清理需覆盖 SQLAlchemy 的成功和 `handle_error` 路径；连接回到池之前不得保留工具级回调。

SQLite 机制依据 [Python sqlite3 progress handler 文档](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_progress_handler)。

### 4. 方言能力与失败关闭

首期只支持 `mysql+pymysql` 和 SQLite。任何其他方言在执行受控 Agent 工具 SQL 前抛出专用 `TOOL_TIMEOUT_UNSUPPORTED`，不允许静默退化为仅协程超时。错误应包含可排障的方言标识，但不包含 SQL 参数、用户查询或敏感数据。

能力判断在 SQL 执行层集中维护，避免每个工具自行实现超时逻辑。SQLAlchemy 事件挂载在应用实际使用的 Engine 上，并只在工具超时上下文存在时生效；无上下文的普通业务 SQL 保持现状。

SQLAlchemy 事件钩子的实现以 [SQLAlchemy Core Events 文档](https://docs.sqlalchemy.org/en/20/core/events.html) 为依据。`ContextVar` 在线程池传播行为以 [Python asyncio.to_thread 文档](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread) 为依据。

## 错误与状态语义

- 数据库中断仅在当前工具截止时间确已到达时映射为 `ToolExecutionTimeout` / `TOOL_TIMEOUT`。其他数据库错误维持现有错误分类，避免把连接中断、权限错误或 SQL 缺陷误判成超时。
- `TOOL_TIMEOUT` 是终止性工具错误：Agent 记录工具调用失败并结束本次任务，不让规划器针对同一调用自动重试。
- Agent 工具轨迹记录 `error_code=TOOL_TIMEOUT`；对用户使用现有安全错误响应格式，不暴露 SQL、参数或驱动堆栈。
- 多意图批量查询把超时记到对应项的 `error_code=TOOL_TIMEOUT`，并遵循当前批处理对独立项继续执行的语义；已完成项和其他独立项结果保留。只有整体任务时限到达时才按现有整体超时处理。
- 若数据库中断后仍需等待 SQLAlchemy/驱动清理，期间不得关闭或重用被工作线程占用的 Session。数据库中断完成并退出执行调用栈后，沿用当前取消清理路径。
- 不自动重试超时工具。用户显式重试仍受现有任务重试和工具权限规则约束。

## 可观测性

- 继续记录现有 `agent_tool_duration_seconds`。
- 在工具轨迹中记录工具名、耗时、超时结果和错误码；禁止记录原始查询参数。
- 增加超时计数指标，标签限制为工具名、数据库方言和结果类别，避免参数、租户 ID 等高基数或敏感标签。
- 方言不支持与真正超时使用不同错误码，便于配置问题与慢查询区分。

## 实现验收条件

1. 工具发出一个超过预算的 MySQL SELECT 时，服务端在预算附近终止语句，调用返回 `TOOL_TIMEOUT`。
2. SQLite 长查询由 progress handler 中断；短查询正常完成。
3. 一个工具内先执行耗时 SQL 再执行第二条 SQL 时，第二条只能使用第一条消耗后的剩余预算，不能重新获得完整预算。
4. 普通 SELECT 与 WITH/CTE 查询正确获得 MySQL 提示；不支持的语句形态不会被不安全地改写。
5. SQL 已完成但工具处理逻辑耗尽预算时，下一条 SQL 执行前立即超时。
6. 正常执行、数据库异常和超时之后，SQLite 连接复用时 progress handler 均已清除。
7. Agent 超时后写入 `TOOL_TIMEOUT` 并停止重规划；多意图只标记超时项，独立项结果不丢失。
8. 未支持方言在发出 SQL 前返回 `TOOL_TIMEOUT_UNSUPPORTED`。
9. 不存在工具超时上下文时，普通业务 SQL 不受新事件逻辑影响。
10. 回归覆盖权限隔离、只读边界、工具参数验证、整体任务超时和现有取消清理语义。

实现测试应使用可控 SQLite 查询与模拟/集成 MySQL 语句验证 SQL 改写和错误映射。真正的 MySQL 服务端中断行为需在可用的 MySQL 8.0 环境确认；若当前开发环境无 MySQL，则记录为集成环境验收项，不以模拟用例声称服务端行为已通过。

## 风险与处理

- MySQL 的执行时长受服务端调度、网络和驱动异常传播影响，返回时间可能晚于配置预算；以 SQL 中断确已发生且 Session 安全收尾作为验收重点。
- optimizer hint 只覆盖 SELECT。工具仍必须保持只读；未来若引入写工具，必须另行设计事务和中断语义。
- CTE、注释、大小写及 SQLAlchemy 生成语句可能影响 SELECT 识别。改写器须基于测试覆盖的安全解析策略；无法识别时快速失败，不执行无界查询。
- SQLite progress handler 只在虚拟机执行期间按指令回调；很少执行 VM 指令但阻塞在外部 I/O 的查询不一定能及时打断。当前 SQLite 仅作为本地/测试方言，生产 MySQL 使用服务端限制。
- 配置值过低可能使合法查询频繁超时；首期默认 15 秒应在实际代表性 Agent 样本中观察并可配置调整。

## 自审记录

- 超时是一次工具调用的绝对预算，避免多条 SQL 逐条重置时限。
- 通过数据库执行层中断 SQL，避免将取消协程误认为停止了工作线程。
- MySQL 和 SQLite 使用不同的数据库原生中断机制；未知方言失败关闭。
- 错误映射依赖截止时间是否已到达，不将所有数据库异常误报为超时。
- 指标与轨迹禁止记录用户参数；工具只读权限仍由现有服务端规则兜底。
- 首期只添加公共超时配置，没有未经证据支持的逐工具预算。
- MySQL 提示时间采用毫秒向上取整，避免向下取整导致服务端提前中断并被错误分类；小于 1ms 时发 SQL 前超时。
