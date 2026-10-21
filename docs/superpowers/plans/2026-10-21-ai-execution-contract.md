# AI 路由与执行契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax.

## Goal

落实已审阅的 AI 路由与执行契约设计：以 `execution_mode` 显式决定查询执行器；将按当前用户权限裁剪的 `CapabilityManifest` 注入路由理解；在现有会话 JSON 状态中保存有版本和生命周期的待澄清状态。保持只读边界、执行时权限复验、route token 绑定，以及 Agent `PendingChoice` 和批次 `BatchChoice` 两套既有交互状态。

## Architecture

- `Understanding` 是模型输出与服务端分派之间的唯一结构化契约。Schema 校验器负责拒绝不可能完整执行的组合；提示词只负责在该契约内选择模式。无效输出最多重新理解一次，仍无效则澄清且不执行。
- `CapabilityManifest` 由服务端从现有 Agent 工具定义、Text2SQL 数据集权限和用户可访问资源范围构造，只传递路由所需的名称、任务、筛选字段和可用性信息，不包含业务记录、数据库 ID 或凭据。它不代替执行层权限检查。
- `pending_clarification` 放入 `AIConversationState.memory_state`，带状态 ID、问题摘要、槽位、问题/选项、创建/过期时间和契约版本。消费答案时重验会话所有权、权限、状态版本和有效期；无效答案保留 pending，有效答案重新路由，取消/切换/过期清理旧 pending。并发写入使用现有 `state_version` 防止迟到覆盖。
- 聊天、`/ai/route`、直接 Agent 启动和批次恢复统一遵循同一执行策略。旧 token 不能被猜测迁移；需提示重新识别。旧会话无 pending 时视为普通新请求。批次和 Agent 原有状态载荷保持独立。
- 不改 STAR 或 README，不实现设计文档列出的 Tool Registry、成本治理、知识库、写工具、Supervisor 等后续能力。本工作区既有订单号、产品聚合槽位、Text2SQL 权限优先级改动需原样保留并覆盖回归。

## Tech Stack

- Python 3、Pydantic Schema、FastAPI 服务、SQLAlchemy 会话与 JSON 状态。
- pytest；现有隔离数据库测试、冻结路由评测 `scripts/evaluate_ai.py`；必要时用现有 Web 前端手动浏览器验收。
- 先检查 `backend/app/modules/ai/` 中当前函数签名及测试夹具，再按测试驱动逐项实现；真实模型评测与离线 CI 测试分别记录。

## Spec

### 执行模式矩阵

| 意图/任务形态 | `execution_mode` | `sub_tasks` 约束 | 结果 |
| --- | --- | --- | --- |
| 能力、指导、问候、取消、澄清、unsupported、采购草稿 | `none` | 空 | 不进入查询执行器；澄清仅保存 pending；采购草稿仍走既有预览/确认边界 |
| 单产品库存、单产品报价、同一产品的库存+报价 | `agent` | 空；目标和槽位表达对象及过滤条件 | 交现有只读 Agent；禁止把多产品折叠到一个目标 |
| 多项彼此独立的库存、报价、analytics 或 document 查询 | `batch` | 2–6 项原子任务；去重 kind 集合必须等于 `tasks` | 交现有批次执行和续跑 |
| 单个业务统计/订单分析 | `query` | 恰好 1 项 `analytics` | 交 Text2SQL |
| 单个化学品资料检索 | `document` | 恰好 1 项 `document` | 交既有文档检索 |
| 同时含可执行查询与不支持写操作，或执行器无法完整覆盖的请求 | `none` | 空 | 整体澄清或拒绝；禁止静默漏项、降级或部分执行 |

校验器还需拒绝：`purpose != query` 却选择查询模式；query 无任务/无可执行模式；batch 少于 2 或多于 6 项；batch 的任务集合与去重子任务类型不一致；agent 含 analytics/document、多产品拆项或 sub_tasks；query/document 子任务数量与类型不符。`Understanding.route` 对 query 直接返回显式模式，不再基于子任务数量推断。

### 逐项实施

- [x] **Task 1 — 固化执行契约行为矩阵（测试先行）**
  - 修改 `tests/test_ai_routing.py`：增加参数化矩阵，覆盖上表全部意图及非法组合、子任务数量边界、模式稳定性、route token 错用户/错问题/错会话/过期；保证现有聚合槽位和订单号回归仍在。
  - 修改 `backend/app/modules/ai/schema.py`：给 `Understanding` 增加受限 `execution_mode` 字段与跨字段校验；修改 `route` 属性为显式返回；合法默认值仅用于兼容非查询历史 fixture，查询缺失模式必须在模型输出校验处显式失败。
  - 修改 `backend/app/modules/ai/routing.py`：更新输出 JSON Schema 与 `ROUTING_PROMPT`，列出执行模式选择规则及上述矩阵；结构不合法时最多重新理解一次，二次失败返回安全澄清结果，不签发可执行 token。
  - 先运行 `cd backend; pytest tests/test_ai_routing.py -q`，确认新契约用例因字段/行为缺失而失败；实现后重跑并要求通过。再运行 `pytest tests/test_ai_order_trace.py tests/test_agent_runtime.py -q`，核实工作区已有修复不回退。

- [x] **Task 2 — 构建按用户权限过滤的能力清单**
  - 先检查 `backend/app/modules/ai/agent_tools.py`、`backend/app/modules/ai/catalog.py`、`backend/app/modules/ai/text2sql.py::_validate_plan` 中现有工具注册、数据集权限与资源过滤的唯一事实来源；将可复用的权限判定抽成集中 helper，避免再造授权规则。
  - 新增 `backend/app/modules/ai/capabilities.py`：定义 JSON 可序列化 `CapabilityManifest` 契约及 `build_capability_manifest(db, user)`；包含版本/稳定摘要、当前允许的任务/工具、可查询数据集及白名单筛选字段、必要的已授权资源范围说明。不得包含业务 ID、数据行、密钥、完整用户权限主体或不可访问能力细节。
  - 新增 `tests/test_ai_capability_manifest.py`：为不同权限角色和资源范围构造 manifest；断言无权数据集/工具不出现，输出不含 ID/业务值；权限撤销后原执行 helper 仍拒绝执行。
  - 修改 `backend/app/modules/ai/routing.py` 和 `backend/app/modules/ai/controller.py`：将 manifest 作为受信路由上下文传入 `/ai/route` 和相应理解入口；不得让客户端提交 manifest。
  - 先运行新增测试并确认失败，再运行 `cd backend; pytest tests/test_ai_capability_manifest.py tests/test_ai_routing.py -q`。

- [ ] **Task 3 — 统一聊天、路由凭据与 Agent 的分派语义**
  - 修改 `backend/app/modules/ai/service.py::_classify_chat_intent` 及同步/流式聊天分派：只根据已经校验的 `Understanding.execution_mode` 选择 batch、Agent、Text2SQL、document 或非查询处理；移除按 `sub_tasks` 数量隐式推断的分派。
  - 修改 `backend/app/modules/ai/agent_runtime.py`：有效 route token 的 Agent 启动复用签发的理解结果；无 token 入口通过相同 manifest、Schema 和校验器重新理解；模式不是 `agent` 时不创建/启动 Agent 任务。
  - 修改 `backend/app/modules/ai/multi_intent.py`：批次入口只接受已验证的 batch 契约，不将不匹配输入裁剪成局部子集；保留成功项、候选版本、失败项重试和 `BatchChoice` 的现有行为。
  - 补充 `tests/test_ai_service.py`、`tests/test_agent_runtime.py`、`tests/test_ai_multi_intent.py`：同一理解结果经 route token、聊天及 Agent 入口时选择相同策略；模式不匹配、票据不匹配或过期时零工具调用；既有只读权限拒绝仍有效。
  - 每个新增用例先确认失败，再按最小修改使其通过；运行以上三组测试，并检查 Text2SQL 和 document 的单任务路径。

- [ ] **Task 4 — 实现版本化待澄清状态**
  - 在 `backend/app/modules/ai/schema.py` 定义 `PendingClarification` 严格结构；字段包括随机 state ID、原问题摘要、待回答槽位、澄清文本、有限选项、创建/过期时间、权限摘要、状态版本与契约版本，不重复保存原问题明文。为避免从问题文本猜槽位，在路由输出契约增加可选 `clarification_slot` 和 `clarification_options`；只有带稳定槽位和 2–5 项有限选项的澄清才持久化。
  - 修改 `backend/app/modules/ai/conversation_store.py`：新增读取、创建/替换、消费和清除 pending 的集中方法；仅对所属会话操作，锁定状态行；以 `state_version` 条件更新检测并发冲突，不覆盖更高版本状态。复用 `AIConversationState.memory_state`，保留同一 JSON 中 `batch_tasks` 等其他键。
  - 修改 `backend/app/modules/ai/service.py` 及必要的 `backend/app/modules/ai/controller.py` 调用点：处理回答时先校验会话所有权、当前权限、state ID/version、契约版本和有效期；答案必须匹配保存选项，之后把原问题、待回答槽位和答案绑定后重新路由。非法答案继续澄清，无效/过期/切换/取消则不执行旧计划并清理状态。`/ai/route` 仅签发含待澄清状态 ID 的短期票据，不提前消费 pending；实际聊天或 Agent 任务接收时以状态版本原子消费。
  - 新增 `tests/test_ai_clarification_state.py`：跨请求续答、只绑定指定槽位、无效回答保持 pending、切换/取消/过期清理、错用户/错会话拒绝、并发迟到写入不覆盖、旧会话无 pending 可继续。
  - 先验证生命周期测试失败，再通过实现；运行新增测试及 `tests/test_batch_continuation.py`，确认澄清状态不合并或破坏批次和 Agent 候选状态。

- [ ] **Task 5 — 清理错误恢复和旧凭据兼容路径**
  - 在 `backend/app/modules/ai/routing.py` 为 route token 加入契约版本；旧版本 token、签名无效、绑定上下文不符统一要求重新识别，不尝试推断缺失 `execution_mode`。
  - 修改 `backend/app/modules/ai/controller.py`、`backend/app/modules/ai/agent_runtime.py`：错误模式、manifest 不包含目标能力、权限执行期被撤销时不启动工具，返回一致的拒绝/澄清结果；可操作错误避免暴露内部工具或授权主体详情。
  - 保持 `backend/app/modules/ai/conversation_store.py` 对会话删除的级联清理语义；pending 与消息同一会话生命周期，删除会话后无残留可续用状态。
  - 添加/更新兼容测试覆盖旧会话 JSON、旧任务 payload、旧 route token、过期 token、执行期间撤权、删除会话、草稿确认不被路由模式绕过；运行 `tests/test_ai_query_isolation.py`、`tests/test_ai_drafts.py`、`tests/test_ai_task_management.py`（若本地隔离数据库可用）。

- [ ] **Task 6 — 冻结评测、前端澄清路径与全量验收**
  - 更新现有离线路由评测题集及 `scripts/evaluate_ai.py`（若其契约断言确需调整），加入库存、报价、同品组合、多产品、analytics、document、澄清、unsupported、采购草稿和混合写读请求的代表样本；样本同时断言 `execution_mode`、任务结构和不可执行请求零工具调用。
  - 运行 `cd backend; pytest tests/test_ai_routing.py tests/test_ai_service.py tests/test_ai_multi_intent.py tests/test_agent_runtime.py tests/test_ai_clarification_state.py tests/test_ai_capability_manifest.py -q`、既有兼容测试，以及 `python scripts/evaluate_ai.py`。记录实际数据库配置；超时/跳过按未通过或未验证报告，不重标为通过。
  - 在浏览器沿用 `frontend-design/apps/web-chemicalops/src/views/ai/workspace/index.vue` 现有聊天模板走查澄清、回答、取消及 token 流程；只有发现前端请求契约确需改动时，才按现有模板最小修改该组件和对应测试。记录浏览器是否实际验收。
  - 对照设计文档的成功标准、安全边界和非目标逐项自查；运行 `git diff --check`，核对所有既有未提交文件仍保留且没有改动 STAR/README。

## Global Constraints

- 每个任务必须采用测试驱动：先写能揭示缺失行为的测试，运行并确认失败原因是预期行为，再实现，随后运行相应测试。不得因环境挂起把用例算作通过。
- 所有数据库权限、资源范围、业务状态、参数和路由凭据校验在服务端执行。Manifest、提示词和模型输出不构成授权。任何失败、澄清或模式冲突都不得先运行部分工具。
- 只读 Agent、Text2SQL 数据集/仓库范围、证据重验、候选版本、批次部分成功与重试、草稿显式确认必须保留。
- 原问题和业务结果不得作为新增日志明文字段；清单只含模型选路所需的最少元数据。
- 保留所有既存工作区变更和用户文档；不自动编辑 STAR/README，不创建数据库迁移，除非实现证明现有 `memory_state` 无法提供并发一致性。
- 按项目提交规范分目的组织 Conventional Commit（type/scope 英文，说明中文）；只有得到明确提交授权后才提交。

## Review Focus

1. 非 `query` 意图误带 `execution_mode` 或查询意图缺少模式时，Schema 是否在工具调用前统一失败关闭；重试失败是否不会签发可执行票据。
2. batch 任务超过 6 项、种类集合不一致或夹带不支持写操作时，是否可能被静默截断、转给 Agent 或执行可行子集。
3. Manifest 是否可能暴露未授权数据集/工具、数据库主键、仓库标识或业务记录；权限撤销后执行层是否仍复验并拒绝。
4. pending clarification 的并发回答、重复提交、跨用户/会话复用、权限变更、过期和“切换但模型判断不明确”是否可能恢复旧计划或覆盖较新状态。
5. route token 契约版本变化、旧任务 payload、旧会话无 `pending_clarification`、数据库状态表缺失时，兼容处理是否安全且不会静默推测模式。

## Plan Self-Review

- 覆盖已批准设计的显式执行模式、能力清单、待澄清状态、token 兼容、安全边界和全部验收类别；非目标仍保持范围外。
- 所有任务列出具体文件、调用关系、测试和通过标准，并要求先确认测试失败；跨任务依赖顺序为契约 → manifest → 分派 → 澄清状态 → 兼容 → 验收。
- 对数据库隔离测试挂起、旧 token 与权限撤回的失败模式均有明确检查，不把未运行的真实模型/浏览器测试表述为通过。
- 计划未修改应用代码；工作区既有订单号、聚合槽位、Text2SQL 权限和用户文档保持为必须保护的输入状态。
