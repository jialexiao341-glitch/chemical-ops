# ChemicalOps Agent Harness 下一阶段任务单

> 文档定位：交给 Codex 执行的任务单，不是验收报告，也不替代现有架构文档。
>
> 使用方式：按 T1 → T2 → T3 → T4 → T5 顺序执行；每个任务独立验收后再进入下一个。后台收尾任务单列，不混入本 sprint。

---

## 0. 一句话目标

后台业务面已经基本齐全，本阶段不再横向加模块；用约两周给 Agent 补上“可测量、可版本化、可恢复、上下文可控”的 harness 控制面。

这里的 harness 指模型之外、让 Agent 可靠运行的那层控制面：上下文装配、工具执行、状态与恢复、评测与版本、可观测与成本。不是重写 LangGraph，也不是更换 Agent 框架。

---

## 1. 当前基线

实现位置与现状：

- Agent 运行时：`backend/app/modules/ai/agent_runtime.py`，LangGraph `plan → execute` 循环，静态只读工具目录，服务端多候选消歧、证据校验、任务取消与队列 checkpoint。
- 工具治理：`backend/app/modules/ai/agent_tools.py`，每个工具已有 `version`、`risk`、`retry_policy`、`idempotent`、`cost_class`、`quota_class` 元数据。
- 权限清单：`backend/app/modules/ai/capabilities.py`，按 RBAC 与资源范围生成 `CapabilityManifest`。
- 多意图：`backend/app/modules/ai/multi_intent.py`，有上限的只读批次、依赖执行与部分结果。
- 上下文：`agent_runtime.py` 当前保留最近 6 轮、旧消息 1200 字，`_fit_planner_context` 做三级压缩；配置为 `agent_context_max_chars=18000`、`agent_max_total_tokens=65536`。
- 失败处理：LLM 只重试 429 与连接未建立错误；读超时/断流不重放；队列对 transient 异常做有界重试；Planner 的 JSON 格式错误只修复一次；工具 SQL 超时 15 秒；工具 `retry_policy=MANUAL_ONLY`。
- 评测：`backend/app/modules/ai/evaluation.py` 的确定性套件，以及 `scripts/evaluate_intent_routing.py`、`scripts/evaluate_agent_tasks.py`、`scripts/evaluate_agent_business.py` 等真实模型评测脚本；CI 已跑离线 fixture 与全量 pytest。

当前缺口：

1. 提示词散在多个文件，没有统一名称、版本、hash 和快照测试。
2. 任务没有统一的运行元数据，无法从 trace 直接回答“用了哪个 prompt/模型、上下文多大、重试几次、为什么失败”。
3. 失败只有 `error_code`，没有错误分类和用户恢复建议。
4. 上下文按字符裁剪，不是 token 预算；长会话和大会话结果仍可能触发 `CONTEXT_LIMIT`。
5. 评测报告不能直接对比，改提示词或上下文后缺少可追溯的回归证据。

---

## 2. 总目标与边界

### 2.1 本阶段目标

- 提示词可登记、可追溯、可快照。
- 每个任务有统一运行元数据。
- 每个失败有错误分类和恢复建议。
- 上下文按 token 预算装配，并保留结构化摘要。
- 评测报告可对比，能指出具体退化用例。

### 2.2 硬约束

- 不重写 LangGraph / Agent Runtime。
- 不修改现有提示词正文；T1 只做登记与 hash。
- 不新增第三方依赖。
- 权限、状态、金额、审批、幂等、写入边界继续由服务端强制校验，不依赖提示词。
- 不自动 `git commit` / `git push`，只改工作区并运行测试。
- 不改 `docs/项目介绍与成果（STAR）.md` 和 `README.md`。
- 不为了“跑绿”修改测试断言；环境问题单独说明。

---

## 3. 任务总览

| ID | 任务 | 优先级 | 预估 | 依赖 |
| --- | --- | --- | --- | --- |
| T1 | Prompt Registry：提示词注册表 + 快照测试 | P0 | 2 天 | 无 |
| T2 | Trace v2：任务运行元数据 | P0 | 2 天 | T1 |
| T3 | Error Policy：错误分类 + 恢复建议 | P0 | 1.5 天 | T2 |
| T4 | Context Assembler：token 感知的上下文装配 | P1 | 3 天 | T2 |
| T5 | Eval Gate：评测报告对比 + 回归门禁 | P1 | 1.5 天 | T1、T4 |

建议排期：T1 第 1–2 天，T2 第 3–4 天，T3 第 5 天，T4 第 6–8 天，T5 第 9–10 天。

---

## 4. 任务详情

### T1：Prompt Registry（不改文案）

**目标**

把现有提示词登记成有名称、版本、hash 的注册表，让后续改动可追溯、可快照。

**改动**

- 新增 `backend/app/modules/ai/prompt_registry.py`：
  - `PromptSpec(name, version, module, attribute)`。
  - `PROMPT_SPECS` 覆盖以下 8 个名称：
    - `routing` → `routing.ROUTING_PROMPT`
    - `planner` → `agent_runtime.PLANNER_PROMPT`
    - `system` → `agent_prompt.SYSTEM_PROMPT`
    - `text2sql_plan` → `agent_prompt.TEXT2SQL_PLAN_PROMPT`
    - `result_rewrite` → `agent_prompt.RESULT_REWRITE_PROMPT`
    - `fallback_guidance` → `agent_prompt.FALLBACK_GUIDANCE_PROMPT`
    - `context_stream` → `context_stream.PROMPT`
    - `guidance` → `agent_prompt.GUIDANCE_PROMPT`（见下一条）
  - `guidance` 目前是 `service.py` 里的内联 `system_prompt`，T1 先把它提取为 `agent_prompt.GUIDANCE_PROMPT`（正文与现有字符串逐字一致，包含 `REPLY_STYLE`），`service.py` 改为引用该常量，再由注册表登记。
  - `get_prompt(name)` 使用 `importlib.import_module` 懒加载，避免循环导入。
  - `prompt_version(name)` 返回形如 `routing@1-<sha8>`。
  - 只在函数内调用 `get_prompt` / `prompt_version`，不要在模块导入时调用，避免 `agent_runtime ↔ prompt_registry` 循环导入。
  - 不复制提示词正文，只引用原常量；正文仍留在原文件。
- 新增 `tests/test_ai_prompt_snapshots.py`：
  - 从 `tests/fixtures/prompt_hashes.json` 读取期望 hash。
  - 断言每个 prompt 的 hash 与 fixture 一致。
  - 不一致时输出明确提示：提示词已变更，请审阅并更新快照，同时跑评测对比。
- 新增 `tests/fixtures/prompt_hashes.json`，首次由当前文本生成。

**验收**

- 8 个 prompt 全部可 `get_prompt`，文本与改动前实际发送的文本逐字一致。
- `prompt_version` 多次调用稳定；修改文本后 hash 变化。
- 无循环导入；`pytest tests/test_ai_prompt_snapshots.py` 通过。
- `git diff` 中提示词文本只允许位置移动（`guidance` 从内联提取为常量），不允许内容或语义变化。

**提交信息**

```text
refactor(ai): 建立提示词注册表与快照测试
```

**注意**

- 快照测试的意义是“变更必须被显式审阅”，不是阻止变更。
- 更新快照时必须同时说明改了什么、为什么改、跑了哪组评测。

---

### T2：Trace v2（任务运行元数据）

**目标**

每个 Agent 任务都能回答“用了哪个 prompt、哪个模型、上下文多大、重试几次、为什么失败”，且不暴露提示词正文和模型思维链。

**改动**

- `backend/app/modules/ai/agent_runtime.py`：
  - `RunState` 增加 `run_meta: dict`，结构建议：

    ```python
    {
        "prompt_versions": {"routing": "...", "planner": "...", "result_rewrite": "..."},
        "model": {"provider": "...", "name": "..."},
        "context": {"estimated_tokens": 0, "max_tokens": 0, "truncated_sections": []},
        "retries": {"llm": 0, "tool": 0},
        "error": {"code": None, "class": None, "recovery": None},
    }
    ```

  - `_persist` 把 `run_meta` 写入 `AIAgentTask.payload`；队列 checkpoint 只存必要子集，避免膨胀。
  - `_drive_impl` 在路由、规划、工具执行、异常收口处更新字段。
  - 只记录 prompt 名称/版本/hash，不记录正文。
- `backend/app/modules/ai/schema.py`：
  - `TaskRead` 增加 `run_meta: dict = Field(default_factory=dict)`。
- `get_task` / `list_tasks` 从 `payload.get("run_meta", {})` 填充；旧任务返回空 dict。
- 可选：前端任务详情页展示“模型 / 版本 / 上下文 / 错误分类”，但必须复用现有任务详情模板，不新写样式。

**验收**

- 成功任务有 `prompt_versions`、`model`、`context`。
- 失败任务有 `error.code`；`error.class` 和 `error.recovery` 在 T2 允许为 `None`，由 T3 分类策略填充。
- 旧任务读取不报错；API 向后兼容。
- 现有 `tests/test_agent_runtime.py`、`tests/test_agent_queue_runtime.py` 通过。

**提交信息**

```text
feat(ai): 增加 Agent 运行元数据与提示词版本记录
```

**注意**

- 不要记录 prompt 正文、原始模型输出、异常堆栈或用户敏感全文。
- `run_meta` 仅用于可观测和验收，不作为权限或业务判断依据。

---

### T3：Error Policy（错误分类 + 恢复建议）

**目标**

把现有 `error_code` 映射成“错误类别 + 用户下一步”，但不改变现有重试机制，更不新增通用重试框架。

**改动**

- 新增 `backend/app/modules/ai/error_policy.py`：
  - `ErrorClass`：`TRANSIENT_INFRA`、`AMBIGUOUS_TIMEOUT`、`BUSINESS_INVALID`、`AUTHORIZATION`、`FORMAT`、`BUDGET`、`TOOL_TIMEOUT`、`UNKNOWN`。
  - `RecoveryAction`：`RETRY`、`NARROW_SCOPE`、`REAUTH`、`FIX_INPUT`、`WAIT`、`CONTACT_SUPPORT`。
  - `classify(error_code, exc=None) -> (ErrorClass, RecoveryAction, hint)`。
- `agent_runtime._drive_impl` 异常处理：
  - 保留现有 `error_code` 和 `reply` 文案。
  - 写入 `run_meta["error"]`。
  - trace 的 `stop` 步骤增加 `error_class`、`recovery_action`。
- 策略建议（T3 不保证执行）：
  - `TRANSIENT_INFRA` 建议最多一次有界重试；`AMBIGUOUS_TIMEOUT` 建议等待并核对状态，不自动重试。
  - `BUSINESS_INVALID` / `AUTHORIZATION` 建议不重试；`TOOL_TIMEOUT` 建议缩小范围，不自动重跑。
  - 写操作/动作提案建议不自动重试；实际执行边界以现有实现为准。
  - trace 标明恢复动作只是建议，不代表当前队列会按分类执行。

**建议映射**

| error_code | ErrorClass | RecoveryAction | 重试建议（T3 不保证执行） |
| --- | --- | --- | --- |
| `STEP_LIMIT` | `BUDGET` | `NARROW_SCOPE` | 否 |
| `CONTEXT_LIMIT` | `BUDGET` | `NARROW_SCOPE` | 否 |
| `INVALID_EVIDENCE` | `BUSINESS_INVALID` | `FIX_INPUT` | 否 |
| `INCOMPLETE_TASK` | `BUSINESS_INVALID` | `FIX_INPUT` | 否 |
| `REPEATED_TOOL` | `BUSINESS_INVALID` | `NARROW_SCOPE` | 否 |
| `TOOL_ERRORS` | `BUSINESS_INVALID` | `FIX_INPUT` | 否 |
| `INTENT_MISMATCH` | `BUSINESS_INVALID` | `FIX_INPUT` | 否 |
| `TOKEN_BUDGET_EXCEEDED` | `BUDGET` | `NARROW_SCOPE` | 否 |
| `TOOL_TIMEOUT` | `TOOL_TIMEOUT` | `NARROW_SCOPE` | 否 |
| `TOOL_TIMEOUT_UNSUPPORTED` | `TOOL_TIMEOUT` | `CONTACT_SUPPORT` | 否 |
| `TASK_TIMEOUT` | `BUDGET` | `NARROW_SCOPE` | 否 |
| `PERMISSION_DENIED` | `AUTHORIZATION` | `REAUTH` | 否 |
| `MODEL_FORMAT_ERROR` | `FORMAT` | `RETRY` | 否（一次格式修复已用尽） |
| `DATABASE_ERROR` | `TRANSIENT_INFRA` | `RETRY` | 建议有界重试 |
| `MODEL_SERVICE_ERROR` | `TRANSIENT_INFRA` | `WAIT` | 建议仅对安全连接失败 / 429 有界重试 |
| `INTENT_SERVICE_ERROR` | `TRANSIENT_INFRA` | `WAIT` | 建议仅对安全连接失败 / 429 有界重试 |
| 模型响应超时或连接中断 | `AMBIGUOUS_TIMEOUT` | `WAIT` | 建议不自动重试 |
| `RUNTIME_ERROR` | `UNKNOWN` | `CONTACT_SUPPORT` | 否 |
| `UNSUPPORTED_REQUEST` | `BUSINESS_INVALID` | `FIX_INPUT` | 否 |

**测试**

- 新增 `tests/test_ai_error_policy.py`：
  - 覆盖上述全部 `error_code` 的映射。
  - 故障注入：429、连接失败、读超时、非法 JSON、撤权、工具超时。
  - 断言分类和建议正确，不断言队列重试次数。
- 现有运行时测试通过；不改变现有重试次数和超时配置。

**T3b 已处理**：`transient()` 仅将连接尚未建立的安全错误（ConnectError、ConnectTimeout、PoolTimeout、ConnectionError、OperationalError）和可重试状态码视为可重试；读超时/断流不再自动重放，由错误策略给出核对建议。该约束由 `tests/test_task_queue_retry_classification.py` 覆盖。

**提交信息**

```text
feat(ai): 增加 Agent 错误分类与恢复策略
```

---

### T4：Context Assembler（token 感知的上下文装配）

**目标**

把“按字符裁剪”升级为“按 token 预算装配 + 结构化摘要”，让长会话和大会话结果不再直接 `CONTEXT_LIMIT`。

**改动**

- 新增 `backend/app/modules/ai/context_assembler.py`：
  - `estimate_tokens(text)`：CJK 按 1 字约 1 token，ASCII 按 4 字符约 1 token，保守上取整。
  - `ContextStats`：`estimated_tokens`、`max_tokens`、`truncated_sections`。
  - `assemble_planner_context(payload, *, max_tokens, max_chars) -> (str, ContextStats)`。
  - 结构化摘要：从 `memory_state` 提取 goal、focus、slots、pending、evidence_ref，只保留必要字段；`recent_context` 只留最近 3 条、每条 320 字。
  - 保留现有顺序：目标/当前问题 → 已核验对象 → 本轮证据步骤 → 工具结果摘要。
  - 每个工具结果有独立 token 配额；超出只保留摘要字段和证据引用。
- `agent_runtime._fit_planner_context` 改为调用新组件；保留函数名作为兼容包装，避免测试和调用方断裂。
- `backend/app/core/config.py` 增加：
  - `agent_context_max_tokens: int = 12000`（新主预算）。
  - 保留 `agent_context_max_chars` 作为最终硬上限。
- 记录 `run_meta["context"]` 和指标：
  - `metrics.observe("agent_context_tokens", ...)`
  - `metrics.increment("agent_context_truncated", labels={"section": ...})`

**验收**

- 构造 20 轮对话 + 100 行工具结果 + 5 个工具步骤，不再抛 `CONTEXT_LIMIT`。
- 短任务上下文与现有行为基本一致；现有 Agent 测试通过。
- token 估算单元测试覆盖中英文、空串、超长串；若模型返回 `usage.prompt_tokens`，应校验“装配上下文估算 + 固定开销”落入实际值的 80%–150% 区间。固定开销指系统提示词与工具 Schema，按模型/工具集一次性标定；直接用上下文估算对比整段 `prompt_tokens` 会系统性偏低，不能作为验收口径。
- v1 不新增 LLM 摘要调用，使用确定性摘要，避免额外成本和不确定性。

**测试**

- 新增 `tests/test_ai_context_assembler.py`。
- 扩充 `tests/test_ai_context.py` 的长会话用例。
- 回归 `tests/test_agent_runtime.py`、`tests/test_ai_routing.py`。

**提交信息**

```text
feat(ai): 引入 token 感知的上下文装配器
```

**注意**

- 不要通过简单删除历史消息来“解决”上下文问题；结构化目标和已核验对象必须保留。
- 上下文装配只影响送给模型的内容，不影响证据、权限和业务事实。

---

### T5：Eval Gate（评测报告对比 + 回归门禁）

**目标**

让“改提示词/上下文”有可对比的基线，能指出具体哪些用例变差，而不是只看一个总准确率。

**改动**

- 新增 `scripts/compare_eval_reports.py`：
  - 输入两份 JSON，支持 `scripts/evaluate_intent_routing.py`、`scripts/evaluate_agent_tasks.py`、`scripts/evaluate_agent_business.py` 的输出结构。
  - 输出：总通过率变化、按用例的 PASS→FAIL / FAIL→PASS 列表、安全用例回归。
  - `--fail-on-regression`：有回归或安全失败时返回非 0。
- 新增 `tests/test_compare_eval_reports.py`：用两份小 fixture 验证对比逻辑。
- CI 不跑真实模型；新测试自动进入现有 `pytest` 全量步骤。
- 可选：新增 `scripts/run_eval_suite.py`，按顺序跑路由契约 + Agent 任务 + 业务场景，生成 baseline/candidate 两份报告。时间不够可先不做。

**验收**

- `python scripts/compare_eval_reports.py --baseline a.json --candidate b.json --fail-on-regression` 能正确退出。
- 报告中能看到具体退化用例，不只是一个百分比。
- 不发起任何网络请求。

**提交信息**

```text
test(ai): 增加评测报告对比与回归门禁
```

---

## 5. 验证命令

```powershell
$env:PYTHONPATH='backend'

# T1–T3 快速回归
.\.venv\Scripts\python.exe -m pytest -q tests/test_ai_prompt_snapshots.py tests/test_agent_runtime.py tests/test_ai_error_policy.py

# T4 上下文回归（不需要真实模型）
.\.venv\Scripts\python.exe -m pytest -q tests/test_ai_context.py tests/test_ai_context_stream.py tests/test_ai_context_assembler.py

# 离线门禁
python scripts/check_evaluation_fixtures.py

# 编译检查
python -m compileall -q backend/app tests
```

说明：本地 MySQL 未 seed 时，部分集成测试会因缺少 `BuyerUser` 等账号失败，这是环境问题；最终以 CI 的 MySQL 初始化 + seed 为准。

---

## 6. Definition of Done

每个任务完成必须满足：

- 只改任务单列出的文件/模块；额外改动已在回复中说明原因。
- 新逻辑有单元测试；原有相关测试不回归。
- 不新增依赖，不修改提示词正文。
- API 向后兼容；新增字段可缺省。
- 代码注释使用中文，风格与现有模块一致。
- 不执行 `git commit` / `git push`。
- 回复中列出：改了哪些文件、测试结果、未覆盖的边界。

---

## 7. 本阶段明确不做

- 不重写 LangGraph / Agent Runtime。
- 不统一 Agent 与批次执行路径；等 T2/T5 的数据证明混合请求占比后再做。
- 不增加通用自动重试，不重试写操作。
- 不做 Supervisor–Specialist、多 Agent、动态工具、运行时自改提示词。
- 不改提示词正文、不改 STAR/README。
- 不为了“看起来完整”新增无业务价值的 CRUD。

---

## 8. 后台收尾（不在本 sprint）

以下事项不影响 Agent sprint，Codex 不要顺手改：

| 事项 | 说明 | 建议 |
| --- | --- | --- |
| 审计日志查询 | `sys_audit_logs` 目前只写不读，没有查询接口和页面 | 新增 `system.audit.read` 权限、查询 API、列表页；复用现有列表模板 |
| 空环境部署/恢复 | Compose、备份恢复脚本已有，但未做空环境验收 | 单独做部署演练，不混入本 sprint |
| 代理/NAT 登录锁 | B-P1-05 仍待处理 | 需要真实代理/NAT 环境确认 |
| 业务纵深 | 部分到货/取消剩余量、库存预留/冻结/释放等 | 属于产品线，不是后台管理完善度问题 |

---

## 9. 给 Codex 的执行指令（可直接粘贴）

```text
按本任务单顺序执行 T1 → T2 → T3 → T4 → T5，不要跳任务、不要扩大范围。

每个任务开始前：
1. 先读相关文件和现有测试，确认当前实现。
2. 只改任务单列出的文件/模块；需要额外改动时先说明原因。
3. 不改提示词正文、不加依赖、不 commit/push。

每个任务完成后：
1. 运行该任务的测试命令。
2. 在回复里列出：改了哪些文件、测试结果、未覆盖的边界。
3. 等我确认后再进入下一个任务。

遇到与任务单冲突的现状（例如函数已被重构、测试结构与描述不符），先停下来说明，不要自行改设计。
```

---

## 10. 验收记录

| 任务 | 状态 | 验收人 | 备注 |
| --- | --- | --- | --- |
| T1 Prompt Registry | 已完成 |  | 实现为 prompt_registry.py 与快照测试；真实模型回归尚未重跑 |
| T2 Trace v2 | 已完成 |  | 已补充路由票据版本记录及错误分类保留回归；真实模型和完整 MySQL 环境尚未验收 |
| T3 Error Policy | 已完成 |  | 分类和恢复动作仅为建议；队列 transient 已收敛为安全连接错误，读超时/断流不自动重放 |
| T4 Context Assembler | 已完成 |  | 口径修正为“固定开销 + 装配估算”：固定开销为系统提示词与工具 Schema，按模型/工具集一次性标定。用 2026-11-09 的 11 个带 usage 样本复算，`estimated_tokens/prompt_tokens` 原始为 0.369–0.581；扣除中位数 1952 的固定开销后为 0.924–1.033，落在 80%–150% 内。未新增真实模型调用 |
| T5 Eval Gate | 已完成 |  | `scripts/compare_eval_reports.py` 支持三类评测报告对比、逐用例回归清单与 `--fail-on-regression`；新增 `scripts/run_eval_suite.py` 与 `scripts/eval_prompt_gate.py`。2026-11-11 验证：注入一条 PASS→FAIL 后门禁返回 2 并列出退化用例；planner 提示词变更后已重建基线 `routing@1-5531c235__planner@1-2911a494`，业务报告未重跑并在 `manifest.not_run` 记录 |
