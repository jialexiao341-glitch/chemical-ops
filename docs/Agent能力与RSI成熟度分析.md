# Agent 能力与 Harness/RSI 成熟度分析

> 依据当前代码核对（commit `d6c7056` 及未提交的 P0-1 变更），不把“有接口、有测试”等同于“已验收”。量化数据注明来源与口径。

## 1 结论摘要

| 维度 | 现状 | 成熟度 |
| --- | --- | --- |
| Agent 只读能力 | 15 个工具覆盖主数据、库存、报价、申请、订单、到货、质检、对账、供应商与异常 | 可用 |
| Agent 写入能力 | 11 个动作处理器，全部经提案预览 + 显式确认 | 可用，边界收紧 |
| 页面上下文 | 7 类业务对象，服务端按权限重读 | 覆盖首批 |
| 评测工程 | 四套件各 3 轮：170 STABLE_PASS / 5 UNSTABLE / 0 STABLE_FAIL，门禁四态裁决 | M2 已判定 |
| 自改进（RSI） | 候选可人工生成；对照实验与配对显著性可用，无自动生成 | M3 中段 |

一句话：**Agent 已经能干活，评测已经能判定，但还不能系统性地提出并证明自己的改进**。

## 2 Agent 能力地图

### 2.1 运行时

```
用户问题
  → routing（意图识别，prompt routing@1-5531c235）
  → planner（规划与子任务，planner@1-2911a494）
  → tools（只读执行，按权限裁剪）
  → 回答 / 澄清 / 提案
  → 提案预览（预览版本 + 幂等键）
  → 用户显式确认
  → action_handler（领域服务 commit=False 预检 → 提交）
  → 账本记录执行结果
```

- 任务由 `documents` / `agent` 两个 Worker 队列消费，进程内执行，可取消、可重试、可续跑。
- 预算账本：超限零请求，任务中断后用量仍可对账。
- 幂等：同内容失败重试复用幂等键，服务端不重复建提案。
- 业务事件重放不重复通知、不重复建任务。

### 2.2 只读工具（15 个）

| 领域 | 工具 | 说明 |
| --- | --- | --- |
| 主数据 | `catalog.search_products` | 名称/编码/CAS/别名找规格，多候选必须让用户选 |
| 库存 | `inventory.query_available` | 按产品查可见仓库余额，按单位合计并保留明细 |
| 库存 | `inventory.replenishment_plan` | 安全库存、可用量、在途采购、未完成补货算缺口，只读 |
| 报价 | `supplier_quotes.find_rfq_items` | 定位可见询价明细 |
| 报价 | `supplier_quotes.compare` | 最新有效报价比较，含成本候选与交期/账期/质量风险 |
| 采购申请 | `purchase_requests.get_by_no` | 精确编号读取申请与明细 |
| 采购订单 | `purchase_orders.trace_by_no` | 跨环节追溯 |
| 采购订单 | `purchase_orders.search` | 按单号/供应商/状态/日期检索可见订单 |
| 质量 | `quality_acceptances.get_by_no` | 验收事实、报告核对、人工复核、冲突 |
| 仓储 | `deliveries.get_by_no` | 收货事实、短交、单证状态 |
| 财务 | `finance_reconciliations.get_by_no` | 行级数量金额、发票匹配、来源差异、付款上限 |
| 供应商 | `suppliers.get_by_code` | 合作状态与基本资料 |
| 供应商 | `suppliers.profile` | 订单/到货/质检/异常/财务进度汇总，按权限裁剪 |
| 运营 | `exceptions.search` | 异常列表检索 |
| 运行时 | `evidence.read` | 分页读取已保存轨迹，重校验权限 |

### 2.3 写入动作（11 个处理器）

| 动作 | 业务影响 | 边界 |
| --- | --- | --- |
| `purchase_request.create_draft` | 创建采购申请草稿 | 不自动提交审批 |
| `purchase_request.update_draft` | 修改草稿 | 版本化差异预览 |
| `purchase_request.submit` | 提交审批 | 服务端重验状态与范围 |
| `rfq.create_draft` | 从已审批申请建询价草稿 | 重验来源申请与行项目 |
| `rfq.send` | 发送询价 | 供应商隔离 |
| `rfq.select_quote` | 中选报价 | 需完整可比且唯一最低总成本 |
| `purchase_order.create_draft` | 从询价生订单草稿 | 仅 DRAFT，逐行保存付款条款快照 |
| `purchase_order.submit` | 提交订单审批 | 仅 DRAFT→APPROVING |
| `exceptions.create_task` | 按精确异常编号建处理任务 | 不接受模糊编号 |
| `inventory.create_replenishment` | 创建补货申请草稿 | 正数数量、唯一产品匹配 |
| `deliveries.followup_draft` | 交期催办草稿 | 仅保存账本，不发送 |

共同约束：`confirm=true` + 当前 `preview_version` + 幂等键；确认前重验权限、资源快照与业务状态；Agent 自身不触发确认。

### 2.4 页面上下文（7 类）

采购申请、采购订单、到货单、库存余额抽屉、质量验收核对抽屉、财务对账明细抽屉、供应商编辑抽屉。服务端只接受 `object_type + object_id`，按当前用户重读，不接受客户端快照。

### 2.5 运营与质量

- AI 运行分析：质量聚合（失败阶段、评价冲突、错误码、工具调用、prompt 版本）、反馈看板、成本看板、回归用例管理。
- 失败分类：`TRANSIENT_INFRA` / `BUSINESS_INVALID` / `FORMAT` / `AUTHORIZATION` 等，决定是否可重试与是否计入回归。

## 3 能做什么（按使用者视角）

| 使用者 | 可完成任务 | 当前限制 |
| --- | --- | --- |
| 采购员 | 查库存、比报价、生成申请/询价/订单草稿、提交审批、催交期 | 审批与正式下单仍走人工流程 |
| 仓管 | 查余额、批次、短交、单证状态 | 不推断质检结论 |
| 质量 | 查验收事实、报告核对、冲突 | 不重新判定合格 |
| 财务 | 查对账行、发票匹配、付款上限 | 不执行付款 |
| 管理员 | 看质量/成本/反馈、从差评生成回归用例、批准用例 | 提示词变更需人工 |

## 4 Harness 工程现状

### 4.1 已落地

| 能力 | 实现 | 证据 |
| --- | --- | --- |
| 多套件编排 | `scripts/eval_harness.py`，`--repeat/--resume/--workers`，统一 envelope；resume 默认重跑含基础设施失败的轮次 | 四套件 3 轮实测（2026-11-12） |
| 稳定性判定 | `scripts/eval_stability.py`，Wilson 区间；<5 轮按全通过/全失败；基础设施失败轮次不计入分母 | 170 STABLE_PASS / 5 UNSTABLE / 0 STABLE_FAIL（175 条） |
| 门禁裁决 | `eval_prompt_gate.py`：PASS / FLAKY / REGRESSION / INVALID_RUN / NOT_RUN | 稳定回归、抖动、基础设施、跨模型均有测试 |
| 基础设施失败隔离 | `TRANSIENT_INFRA` 单列，不计回归与安全失败；污染轮次重跑后不混入统计 | business trial-1 33 轮污染重跑、tasks trial-1 1 轮污染重跑 |
| 回归复核 | `--retest-attempts 3`，稳住采样波动 | T04/B044/B052/B115 复跑 |
| 连通性预检 | `--preflight`，模型不可用不发起批量 | 自检通过 |
| 覆盖度约束 | 四份报告缺一即 NOT_RUN | 单元测试 |
| envelope 直读 | `eval_prompt_gate.py --mode envelope` + `eval_harness.py --suite all` | 离线核对 + 脚本测试（详见第 9 节） |
| 结果入库与趋势 | `record_eval_run.py` 幂等入库，`eval_trend.py` 出月度稳定通过率 | 迁移 076 已应用，4 份 envelope / 175 条用例入库，2026-11 稳定通过率 97.1% |
| 变体对照实验 | `scripts/prompt_experiment.py`：配对的 2×2 列联表 + McNemar 精确检验，只读 envelope | 9 项单测（改善/退化/无差异/跨模型/无有效轮次），不写基线 |

用例规模：routing 34、tasks 16、business 120、prod 5，共 175 条；逐用例三轮稳定性见
[四套件三轮稳定性评估](evaluation/stability-all-r3.md)。

### 4.2 缺口

| 缺口 | 影响 |
| --- | --- |
| CI 仍走原始报告口径 | 基线已同时含 raw 报告与 envelope，但 CI 未切换，两套口径短期并存 |
| 3 轮只能区分全过/全败 | 5 条 2/3 用例只能判 UNSTABLE，统计显著性仍需更多轮次 |
| 模型服务抖动 | 首轮 business 污染 33 轮、tasks 污染 1 轮；需重跑取证，不能直接用污染报告判回归 |
| 无分片并行 | 全量一轮约 25–30 分钟，阻塞迭代 |
| 无历史趋势（仅 1 个月数据） | 已入库 2026-11 一个月，跨月对比要等下一次登记后才能回答 |

## 5 RSI 现状

| 环节 | 状态 | 说明 |
| --- | --- | --- |
| 候选来源 | 部分 | 差评与失败任务可生成候选，但需人工点"生成草稿" |
| 候选批量 | 部分 | 评测失败用例可 `--failed-only` 批量转用例（去重 + dry-run）；差评仍需逐条脱敏 |
| 对照实验 | 有（人工发起） | `scripts/prompt_experiment.py` 做配对列联表与 McNemar 精确检验，只读基线、不写基线 |
| 统计显著性 | 有 | 逐用例配对检验给 p 值与改善/退化清单；轮次不足时只给 INCONCLUSIVE |
| 采纳闸门 | 有人工 | `--promote-baseline` 需人工确认 |
| 自动改提示词 | 无（红线） | 设计上不开放 |

结论：RSI 到 **M3 中段**——对照实验与统计显著性已具备，仍缺"自动产出候选、自动跑实验"两环，
以及候选批量转用例的闭环。

## 6 最终目标

### 6.1 三层终态

**T1 业务终态**：采购到付款主链闭环；Agent 只读覆盖 7 类对象；写入仅限 11 个白名单动作且全走提案确认。

**T2 工程终态**：任何提示词/工具/模型变更必须过"四套件评测 → 稳定性判定 → 人工批准"三道闸，无例外；任何基线变更可追溯到一次实验报告。

**T3 自改进终态（RSI）**：系统从差评与失败轨迹自动产出候选（用例、提示词变体、工具描述修正），自动跑对照实验并给出统计结论，人只需批准或驳回。

**红线**：候选可自动生成，基线不可自动写。

### 6.2 完成定义（DoD）

| 判据 | 目标 |
| --- | --- |
| 评测覆盖 | 175 条用例全部可重复采样，单轮 ≤40 分钟 |
| 门禁可信 | 连续 3 次全量无人为干预，结论一致 |
| 回归闭环 | 差评/失败 → 进评测集 ≤1 天，全程留痕 |
| 实验能力 | 任一 prompt 变体可给出逐用例列联表与 McNemar p 值 ✔（`prompt_experiment.py`） |
| 可观测 | 成功率、失败分类、成本、回归修复时长四项可查 |
| 安全 | 无自动改提示词、无自动写基线、无越权写入 |

## 7 差距与路线

| 优先级 | 差距 | 动作 | 判据 |
| --- | --- | --- | --- |
| P0 | ~~门禁未接 envelope~~ 已完成 ✔ | 门禁改读 harness 输出，稳定性直接出 verdict | 同一 envelope 两处结论一致（见第 9 节） |
| P0 | ~~套件稳定性未知~~ 已完成 ✔ | tasks/business/prod 各跑 `--repeat 3` | 逐用例表见 [四套件三轮稳定性评估](evaluation/stability-all-r3.md) |
| P0 | 旧基线与 CI 未迁移 envelope | 真实多轮结果审阅后登记 envelope 基线，再切 `--harness` | CI 按 envelope 口径出结论，不再回退原始报告 |
| P1 | 候选靠手工 | 评测失败用例批量转用例 ✔；差评批量生成仍需逐条脱敏 | 转化 ≤1 天（尚未实测） |
| P1 | ~~无实验框架~~ 已完成 ✔ | `prompt_experiment.py`：变体 × 用例 × N 轮 + McNemar | 逐用例列联表与 p 值已可产出，不写基线 |
| P2 | ~~无趋势~~ 已完成 ✔ | 评测结果入库 + 月度稳定性趋势 | 迁移 076 已应用；2026-11：4 次运行 / 175 条，97.1% 稳定通过 |

## 8 风险与边界

1. **模型服务抖动**：限流会成片污染报告，必须有 `--preflight` 与 `INVALID_RUN` 拦截，禁止用污染报告判回归。
2. **采样波动**：单次判回归必然误报；少于 5 轮只能区分"全过/全败"，更多轮才有统计意义。
3. **Worker 生命周期**：`dev + reload` 会回收 Worker，验收与评测统一用 `--no-reload`。
4. **业务口径未定**：数量/金额/单位口径（P0-03～06）未确认前，相关评测只验证"取数路径"，不验证业务正确性。
5. **写权限**：提案确认只能由前端用户操作触发，Agent 不得自行确认；这是能力边界，不是待办。

## 9 进展（未提交）

P0「门禁未接 envelope」已落地，对应判据“同一 envelope 两处结论一致”：

| 变更 | 实现 | 判定口径 |
| --- | --- | --- |
| 多套件 envelope | `eval_harness.py --suite all --out-dir`，一次产出四套件 `harness-<suite>.json`（默认 `candidate/envelopes/`）；envelope 保留 `safety` 与失败检查项 | `--repeat/--resume` 负责多轮采样与断点续跑 |
| 门禁直连 envelope | `eval_prompt_gate.py --mode envelope` | 复用 `eval_stability.classify`：稳定退化判 REGRESSION，多轮抖动判 FLAKY，基础设施失败判 INVALID_RUN，跨模型阻断，四套件缺一判 NOT_RUN |
| 安全边界 | 安全用例任一轮失败即计入 `safety_failures` | 不按统计区间放宽：19/20 仍被 Wilson 判 `STABLE_PASS`，门禁照样判 REGRESSION |
| 一条命令跑通 | `run_eval_suite.py --harness --repeat N --gate` | 采样后自动按 envelope 判定 |
| 基线登记 | `--promote-baseline` 同时复制 envelope | `manifest.envelopes` / `envelope_meta` 记录文件名、模型、代码版本、轮次 |
| 回归保护 | 评测脚本测试 59 项（含 envelope 门禁 13 项） | 覆盖稳定回归、单轮抖动、基础设施、缺套件、跨模型、安全零容忍、污染轮次重跑、基线合并登记 |

P0「套件稳定性未知」已完成真实采样（2026-11-12，`deepseek-v4.1-flash`，四套件各 3 轮）：

| 套件 | 用例 | 有效轮次 | 排除基础设施轮次 | STABLE_PASS | UNSTABLE | STABLE_FAIL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| routing | 34 | 102 | 0 | 32 | 2 | 0 |
| tasks | 16 | 48 | 0 | 16 | 0 | 0 |
| business | 120 | 360 | 0 | 117 | 3 | 0 |
| prod | 5 | 15 | 0 | 5 | 0 | 0 |

5 条 UNSTABLE 均为 2/3 通过，无稳定失败；逐用例表与污染处置见
[四套件三轮稳定性评估](evaluation/stability-all-r3.md)。采集期间修掉的三个缺陷：

1. `--resume` 原先会静默复用含 `TRANSIENT_INFRA` 的轮次，把模型抖动固化成“2/3 波动”；
   现在默认重跑这类轮次，只有显式 `--reuse-infra` 才复用。
2. business 评测把逐任务原始结果写死在 `.cache/`，只读环境（受限沙箱、只读缓存）下 120 条全为
   `RUNNER_ERROR`；新增 `--scratch-dir`，harness 默认落在输出目录旁的 `.scratch/`。
3. 基础设施失败的轮次原先计入稳定性分母；现在 `eval_stability` 与 envelope 门禁共用
   `classify_case`，排除该类轮次并单列 `excluded_infra`，全部轮次被排除时判 `NO_EVIDENCE`。

下一步（按顺序）：

1. 已完成：envelope 基线登记——`--promote-baseline` 已把四份 `harness-<suite>.json` 写入当前 prompt 版本目录，
   manifest 同时保留原始报告与版本元数据；`--mode envelope` 自比判 PASS。
   未做：CI 切换——`.github/workflows/agent-eval.yml` 仍跑原始报告口径，改为 `--harness --repeat 3 --gate` 后生效。
2. 部分完成：business B001/B032/B033 定向补跑 7 轮，21/21 通过、失败未复现；合并后 9/10，
   Wilson 下界 0.596 仍判 `UNSTABLE`（见 [不稳定用例定向复跑](evaluation/stability-targeted-rerun.md)）。
   routing 两条因评测器不支持单例筛选、需整轮补到 14–15 轮，本次未跑，保持 `UNSTABLE`。
3. 已完成：P1 实验框架 `prompt_experiment.py`——配对 2×2 列联表、McNemar 精确检验、改善/退化清单，
   只读 envelope、不提供 promote；9 项单测覆盖改善、退化、无差异、跨模型阻断与无有效轮次。
4. 已完成：评测失败用例批量转回归用例——`--failed-only/--case-ids` + `--expected-mode auto` + 去重跳过 + `--dry-run`；
   真实业务报告 dry-run 得 12 条唯一候选、20 条重复跳过、0 条推导失败。
   未做：差评批量脱敏。
5. 已完成：P2 结果入库与趋势——`database/migrations/076_ai_eval_runs.sql`、`scripts/apply_migration.py`
   （PowerShell 无 `<` 重定向，统一用内置执行器）、`scripts/record_eval_run.py`（按 envelope 指纹幂等，
   逐用例写入 `ai_eval_case_results`）、`scripts/eval_trend.py`（月度稳定通过率）。
   迁移已应用：4 份 envelope、175 条用例入库，2026-11 稳定通过率 97.1%（170 STABLE_PASS / 5 UNSTABLE）。
   10 项单测覆盖幂等、跨月聚合、按套件过滤、CLI 与迁移语句拆分。

离线核对仍成立：用历史报告合成 envelope 后自比判 PASS，注入 3 轮全失败用例判 REGRESSION；
真实采样已验证四套件都能产出 envelope，且污染轮次被重跑后统计为 0 排除。