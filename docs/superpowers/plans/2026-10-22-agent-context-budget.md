# Agent 上下文预算与历史裁剪实施计划

> **For agentic workers:** 使用 `superpowers:executing-plans` 逐项实施；步骤使用复选框跟踪。

**Goal:** 保证 Agent 在工具结果较大、历史较长时仍能把有用的业务证据放入规划上下文，并将可序列化上下文限制在配置字符预算内。

**Architecture:** 保留任务轨迹中的完整工具证据，只构造有界的临时规划视图。优先保留本轮目标、最新输入、结构化身份/工作流状态和每个步骤的证据摘要；按需缩短历史文本、工具明细与来源列表。仅当保留关键状态后仍无法满足预算时返回现有 `CONTEXT_LIMIT`。

**Tech Stack:** Python、pytest、现有 Agent Runtime。

**Spec:** `docs/Agent功能专项排查报告.md` 的 AG-01 与“AG-01：40K 工具结果 vs 18K 上下文”。

## Global Constraints

- 完整证据继续保留在任务轨迹；裁剪只作用于传给规划器的临时视图。
- 规划器继续使用当前已核验的工具结果、步骤编号和结构化状态；不能将旧证据变成本轮事实。
- JSON 上下文不得超过 `agent_context_max_chars`；无法安全裁剪时沿用 `CONTEXT_LIMIT`。
- 不改变 API、持久化格式、业务工具权限和任务状态机。

## Review Focus

- 单步 100 行库存和长来源列表仍保留完整 totals、总行数、截断标志与步骤身份。
- 多轮聊天压缩不能删除最新请求、当前目标、已核验身份或待选候选。
- 多个大工具结果不能因单项 10 行上限而使整体上下文溢出。
- 规划视图不得修改原始轨迹；摘要数值仍来自完整工具 totals。
- 极长最新输入或工具目录超过预算时必须安全返回 `CONTEXT_LIMIT`，不能无限重试或丢掉当前任务目标。

---

### Task 1: 为工具结果构造稳定的紧凑规划视图

**Files:**
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- `_planner_view(entry: dict) -> dict` 保留步骤标识、工具身份、状态、关键 totals/总数和有限明细。
- `RunState.trace` 原样保留，供 UI、完成摘要和证据验证使用。

- [x] 覆盖 sources 超长但 rows 很少、单条结果字段很大、多步骤结果同时较大；断言规划视图有界且原始证据未变。
- [x] 运行新增用例确认当前实现无法限制这些情况。
- [x] 实现结果与来源独立裁剪、保留 totals 与证据步骤信息。
- [x] 重跑结果视图用例。

### Task 2: 为完整规划请求应用全局字符预算

**Files:**
- Modify: `backend/app/modules/ai/agent_runtime.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- 新建纯函数 `_fit_planner_context(payload: dict, max_chars: int) -> str`，返回合法 JSON；无法在保留关键字段时适配则抛出 `BusinessValidationError("CONTEXT_LIMIT")`。
- `_decide` 使用该函数构造模型输入，并在格式修复重试时对新增字段重新校验预算。

- [x] 覆盖 100 行库存、多步骤大结果、长历史/近期记忆组合；断言规划请求不超过上限，保留当前问题/目标/步骤 ID/totals，且未改变源状态。
- [x] 覆盖预算低于必要结构的情况，确认安全失败为 `CONTEXT_LIMIT`。
- [x] 实现分层裁剪：压缩历史与旧记忆，缩短结果明细/来源，再裁剪冗余结果字段；不丢当前问题、目标、工作流和证据步骤摘要。
- [x] 重跑上下文预算回归及现有 Agent 测试。

### Task 3: 完整回归与最终检查

**Files:**
- Review: `backend/app/modules/ai/agent_runtime.py`
- Review: `tests/test_agent_runtime.py`

- [x] 运行 Agent Runtime 及相关证据/权限回归。
- [x] 检查 `git diff --check` 与最终差异；未做真实模型和浏览器验收时在进度记录中注明。
