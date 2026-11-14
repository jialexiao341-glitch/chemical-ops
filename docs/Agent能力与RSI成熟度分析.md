# Agent 能力与 Harness/RSI 成熟度分析

> 依据当前代码核对（代码截至 `7cbd0b9`，基线 `routing@1-752b1384__planner@1-2911a494`），不把“有接口、有测试”等同于“已验收”。量化数据注明来源与口径。

## 1 结论摘要

| 维度 | 现状 | 成熟度 |
| --- | --- | --- |
| Agent 只读能力 | 15 个工具覆盖主数据、库存、报价、申请、订单、到货、质检、对账、供应商与异常 | 可用 |
| Agent 写入能力 | 11 个动作处理器，全部经提案预览 + 显式确认 | 可用，边界收紧 |
| 页面上下文 | 服务端按权限重读 8 类注册对象（前端详情已接入 7 类）；工作台与详情浮窗均接入 `/ai/route` 上下文消歧与受控提案弹窗；9 场景 × 3 轮专项实测 27/27（叠放修复后待浏览器复验） | 闭环可用 |
| 评测工程 | 当前基线 `routing@1-752b1384__planner@1-2911a494` 四套件各 3 轮：175/175 STABLE_PASS（0 退化/0 基础设施失败），分片并行同机全量 ~30 分钟；门禁四态裁决，Actions 工作流已拆矩阵并行（待首轮触发取证） | M2 已判定（耗时达标） |
| 自改进（RSI） | 已落地后台轮询/`run_rsi_cycle.py` 自动脱敏归集 `DRAFT` 候选、按失败阶段/反馈聚类只读提案，以及一键编排 McNemar 对照实验与门禁报告（严禁自动写基线/改提示词）；待真实反馈样本积累 | M3 → T3 受控闭环（待生产样本） |

一句话：**Agent 已经能干活，评测与受控 RSI 闭环机制已就绪，剩余工作主要为前端叠放与多详情页实机复验、云端 CI 首跑取证与生产反馈样本积累**。

## 2 Agent 能力地图

### 2.1 运行时

```
用户问题
  → routing（意图识别，prompt routing@1-752b1384）
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

### 2.4 页面上下文（服务端 8 类 / 详情页接入 7 类）

采购申请、采购订单、到货单、库存余额抽屉、质量验收核对抽屉、财务对账明细抽屉、供应商编辑抽屉（协议类型另含 `rfq`）。服务端只接受 `object_type + object_id`，按当前用户重读，不接受客户端快照；除只读流式问答 `/ai/context/stream` 外，AI 工作台与详情页浮窗 Copilot（`page-copilot-drawer.vue`）均已接入 `/api/v1/ai/route` 的 `page_context` 绑定、状态/权限硬约束与 `<ActionProposalDetail>` 提案确认弹窗。

### 2.5 运营与质量

- AI 运行分析：质量聚合（失败阶段、评价冲突、错误码、工具调用、prompt 版本）、反馈看板、成本看板、回归用例管理。
- 回归用例：差评/失败任务候选可批量生成，服务端按固定规则脱敏（手机号、邮箱、身份证、银行卡、IP、联系人/单位名称）后入库；候选默认排除 `WORKER_UNAVAILABLE` 等基础设施失败，差评来源保留；产品、供应商等业务实体仍需人工核对，管理员可批量批准后才导出评测集。
- 失败分类：`TRANSIENT_INFRA` / `BUSINESS_INVALID` / `FORMAT` / `AUTHORIZATION` 等，决定是否可重试与是否计入回归。

## 3 能做什么（按使用者视角）

| 使用者 | 可完成任务 | 当前限制 |
| --- | --- | --- |
| 采购员 | 查库存、比报价、生成申请/询价/订单草稿、提交审批、催交期 | 审批与正式下单仍走人工流程 |
| 仓管 | 查余额、批次、短交、单证状态 | 不推断质检结论 |
| 质量 | 查验收事实、报告核对、冲突 | 不重新判定合格 |
| 财务 | 查对账行、发票匹配、付款上限 | 不执行付款 |
| 管理员 | 看质量/成本/反馈、从差评/失败任务批量生成并脱敏回归用例、批量批准用例 | 产品/供应商等业务实体需人工核对；提示词变更需人工 |

## 4 Harness 工程现状

### 4.1 已落地

| 能力 | 实现 | 证据 |
| --- | --- | --- |
| 多套件编排 | `scripts/eval_harness.py`，`--repeat/--resume/--workers`，统一 envelope；resume 默认重跑含基础设施失败的轮次 | 四套件 3 轮实测（2026-11-12） |
| 稳定性判定 | `scripts/eval_stability.py`，Wilson 区间；<5 轮按全通过/全失败；基础设施失败轮次不计入分母 | 170 STABLE_PASS / 5 UNSTABLE / 0 STABLE_FAIL（175 条） |
| routing 长轮次补证 | `eval_harness.py --suite routing --repeat 14`；失败行带 `run_meta.error.class`，污染轮次可自动重跑 | 34/34 STABLE_PASS，476 次请求，0 排除轮次（见 路由评测 14 轮稳定性证据） |
| business 定向补证 | `evaluate_agent_business.py --cases B001 B032 B033 --repetitions 14 --workers 3` | 42/42 通过；与原 2/3 合并 16/17 STABLE_PASS（见 business 定向补证） |
| 门禁裁决 | `eval_prompt_gate.py`：PASS / FLAKY / REGRESSION / INVALID_RUN / NOT_RUN | 稳定回归、抖动、基础设施、跨模型均有测试 |
| 基础设施失败隔离 | `TRANSIENT_INFRA` 单列，不计回归与安全失败；污染轮次重跑后不混入统计 | business trial-1 33 轮污染重跑、tasks trial-1 1 轮污染重跑 |
| 回归复核 | `--retest-attempts 3`，稳住采样波动 | T04/B044/B052/B115 复跑 |
| 连通性预检 | `--preflight`，模型不可用不发起批量 | 自检通过 |
| 覆盖度约束 | 四份报告缺一即 NOT_RUN | 单元测试 |
| envelope 直读 | `eval_prompt_gate.py --mode envelope` + `eval_harness.py --suite all` | 离线核对 + 脚本测试（详见第 9 节） |
| CI 自动门禁 | `.github/workflows/agent-eval.yml`：`--harness --repeat 3 --preflight --require-baseline --gate --fail-on-regression`；结论写 Step Summary，envelope 与日志留档 30 天 | 缺基线在采样前退出（单测）；离线自比 PASS |
| 结果入库与趋势 | `record_eval_run.py` 幂等入库，`eval_trend.py` 出月度稳定通过率 | 迁移 076 已应用，4 份 envelope / 175 条用例入库，2026-11 稳定通过率 97.1% |
| 变体对照实验 | `scripts/prompt_experiment.py`：配对的 2×2 列联表 + McNemar 精确检验，只读 envelope | 9 项单测（改善/退化/无差异/跨模型/无有效轮次），不写基线 |

用例规模：routing 34、tasks 16、business 120、prod 5，共 175 条；逐用例数据见
`docs/evaluation/baselines/<prompt-key>/harness-<suite>.json`（5 条 UNSTABLE 已定向补证，见第 9 节）。

### 4.2 缺口

| 缺口 | 影响 |
| --- | --- |
| CI 首轮实跑未发生 | 工作流已按 envelope 口径改写，但定时/手动运行尚未在 GitHub Actions 产生记录；限流、跨模型、基线缺失这些分支只由单测与本地自比覆盖 |
| 3 轮只能区分全过/全败 | 3 轮采样本身仍只能区分全过/全败；5 条 UNSTABLE 已定向补证（routing 14 轮、business 3 条各 14 轮） |
| 模型服务抖动 | 首轮 business 污染 33 轮、tasks 污染 1 轮；需重跑取证，不能直接用污染报告判回归 |
| 并发受上游限额制约 | business 分片并行与跨套件并行已将 3 轮全量降至约 30 分钟；继续盲目拉高并发仍受模型服务限流制约 |
| 无历史趋势（仅 1 个月数据） | 已入库 2026-11 一个月，跨月对比要等下一次登记后才能回答 |

## 5 RSI 现状

| 环节 | 状态 | 说明 |
| --- | --- | --- |
| 候选来源 | 已有自动采集 | `scripts/run_scheduler.py` 轮询调用 `rsi_cycle.sync_candidate_drafts`、`scripts/run_rsi_cycle.py` 支持定时/手工巡检；从差评与非基础设施失败任务确定性脱敏后幂等入库为 `DRAFT`，绝不自动批准或写基线 |
| 候选批量 | 有（含批量脱敏） | 评测失败用例可 `--failed-only` 批量转用例；差评/失败候选支持自动入草稿及一次确认批量入库，服务端逐条再脱敏 |
| 改进提案 | 有（只读聚类） | `rsi_cycle.build_improvement_proposals` 按真实 `failure_stage` 与 `reason_code` 聚集至 `ROUTING_PROMPT` / `AGENT_TOOL_CONTRACTS` / `PLANNER_PROMPT`，附脱敏纠正摘录与核验命令，`auto_applied=False` |
| 对照实验 | 有（可自动发起） | `scripts/run_rsi_cycle.py --run-experiment` 可编排 `eval_harness` 采样、配对 `prompt_experiment`（McNemar 精确检验）与 `eval_prompt_gate`（envelope 裁决）并输出统一报告，只读不写基线 |
| 统计显著性 | 有 | 逐用例配对检验给 p 值与改善/退化清单；轮次不足时只给 INCONCLUSIVE |
| 采纳闸门 | 有人工 | `review_cases_batch` 与 `--promote-baseline` 均强制人工确认 |
| 自动改提示词 | 无（红线） | 设计上不开放 |

结论：RSI 已完成 **M3 → T3 机制闭环（受控红线内）**——无需人工触发的 `DRAFT` 候选归集、只读改进提案聚类以及对照实验 + McNemar 报告编排均已落地；仍待补齐的是生产环境积累足够 `APPROVED` 差评样本以解除 `NO_PRODUCTION_SAMPLES`，以及 GitHub Actions 云端实跑验证。

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
| P0 | ~~套件稳定性未知~~ 已完成 ✔ | tasks/business/prod 各跑 `--repeat 3` | 逐用例数据见基线 `harness-<suite>.json`；5 条 UNSTABLE 已定向补证（见第 9 节） |
| P0 | ~~旧基线与 CI 未迁移 envelope~~ 已完成 ✔（配置） | envelope 基线已登记；CI 改走 `--harness --repeat 3 --preflight --require-baseline --gate --fail-on-regression` | CI 只读 envelope 出结论，不再回退原始报告；缺基线在采样前失败（真实 Actions 首跑待发生） |
| P1 | ~~差评批量生成仍需逐条脱敏~~ 已完成 ✔ | 候选批量接口 + 服务端确定性脱敏 + 一次确认 + 管理员批量批准；单条提交同样兜底脱敏 | 候选预览与入库文本一致；重复项复用/跳过、批量审阅状态隔离有单测；合成基准只测机器耗时，生产转化 ≤1 天仍未实测 |
| P1 | ~~routing 两条 2/3 只能判 UNSTABLE~~ 已完成 ✔ | 整轮补到 14 轮；routing 失败行补 `run_meta.error.class` 供 harness 自动重跑 | 34/34 STABLE_PASS，两条均 14/14，0 基础设施轮次计入分母（见 [14 轮证据](evaluation/routing-14-round-stability.md)） |
| P1 | ~~business B001/B032/B033 2/3~~ 已完成 ✔ | 定向 14 轮；与 3 轮基线合并 | 42/42 通过；累计 16/17，三条均 STABLE_PASS（见 [定向补证](evaluation/business-unstable-14-round-retest.md)） |
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
| 回归保护 | 评测脚本测试 69 项（含 envelope 门禁 13 项、套件编排 9 项） | 覆盖稳定回归、单轮抖动、基础设施、缺套件、跨模型、安全零容忍、污染轮次重跑、基线合并登记、缺基线不采样 |

P0「套件稳定性未知」已完成真实采样（2026-11-12，`deepseek-v4.1-flash`，四套件各 3 轮）：

| 套件 | 用例 | 有效轮次 | 排除基础设施轮次 | STABLE_PASS | UNSTABLE | STABLE_FAIL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| routing | 34 | 102 | 0 | 32 | 2 | 0 |
| tasks | 16 | 48 | 0 | 16 | 0 | 0 |
| business | 120 | 360 | 0 | 117 | 3 | 0 |
| prod | 5 | 15 | 0 | 5 | 0 | 0 |

5 条 UNSTABLE 均为 2/3 通过，无稳定失败；逐用例数据见基线 envelope，
污染处置见下文。采集期间修掉的三个缺陷：

1. `--resume` 原先会静默复用含 `TRANSIENT_INFRA` 的轮次，把模型抖动固化成“2/3 波动”；
   现在默认重跑这类轮次，只有显式 `--reuse-infra` 才复用。
2. business 评测把逐任务原始结果写死在 `.cache/`，只读环境（受限沙箱、只读缓存）下 120 条全为
   `RUNNER_ERROR`；新增 `--scratch-dir`，harness 默认落在输出目录旁的 `.scratch/`。
3. 基础设施失败的轮次原先计入稳定性分母；现在 `eval_stability` 与 envelope 门禁共用
   `classify_case`，排除该类轮次并单列 `excluded_infra`，全部轮次被排除时判 `NO_EVIDENCE`。

P0「旧基线与 CI 未迁移 envelope」的 CI 部分已切换（未提交）：

| 变更 | 实现 | 判定口径 |
| --- | --- | --- |
| CI 只走 envelope | `.github/workflows/agent-eval.yml` 改为 `run_eval_suite.py --suite all --harness --repeat 3 --business-workers 3 --preflight --require-baseline --gate --fail-on-regression` | CI 不再消费原始报告；结论由 envelope 门禁四态给出 |
| 缺基线快速失败 | `run_eval_suite.py --require-baseline`：按 `eval_prompt_gate.prompt_key()` 校验当前 prompt 版本目录下四份 `harness-<suite>.json` | 缺失即退出 1，不发起 75–90 分钟采样 |
| 模型口径对齐 | 工作流默认模型改为与基线一致的 `deepseek-v4.1-flash`（`https://ai.max66.xyz/v1`） | 换模型仍由门禁判 `INVALID_RUN`，不能把跨模型差异当回归 |
| 取证留档 | 门禁输出写 `$GITHUB_STEP_SUMMARY`；`candidate/envelopes`、逐轮 trial 报告与 `eval-gate.log` 上传 artifact，保留 30 天 | 失败时能定位到具体用例与轮次，不必先重跑 |
| 串行约束 | `concurrency: agent-eval-gate`，不取消进行中的运行 | 两次全量并发会互相限流，成片污染两轮证据 |

验证：`run_eval_suite` 9 项单测（新增“缺基线不采样”“基线齐全才放行”“非 harness 模式拒绝”3 项）；
评测相关 69 项单测全部通过；本地以当前基线自比 `--mode envelope --fail-on-regression` 判 PASS
（routing 32/34、tasks 16/16、business 117/120、prod 5/5）。未做：GitHub Actions 首轮实跑尚未发生，
限流与 `INVALID_RUN` 的真实处置仍需一次定时运行取证。

P1「差评批量脱敏」已落地（未提交）：

| 变更 | 实现 | 安全边界 |
| --- | --- | --- |
| 批量入口 | `POST /ai/regression-cases/batch`（1–50 条）；候选弹窗多选、一次确认，逐条返回 CREATED/REUSED/SKIPPED/FAILED | 单项失败不中断整批；整批仍需 `redacted_confirmed` |
| 确定性脱敏 | `backend/app/modules/ai_agent/shared_utils/redaction.py`：邮箱、身份证、银行卡、手机号、座机、IP、联系人/单位名称按固定规则遮蔽 | 不调用模型；重复执行结果不变 |
| 预览即保存 | 候选接口返回 `redacted_question` 与 `redaction_findings`；前端批量提交使用预览文本 | 服务端再次脱敏，客户端漏改也不会把联系方式写进评测集 |
| 去重与归属 | 批内重复、既有草稿复用、已审阅或同来源任务已有用例跳过；非管理员仅本人任务 | 管理员可跨用户；状态仍走既有审阅流 |
| 候选过滤 | 候选默认跳过 `TRANSIENT_INFRA` / `AMBIGUOUS_TIMEOUT` 失败；差评来源保留，`include_infra` 可显式审计 | 避免 worker 宕机、模型服务抖动被做成能力回归 |
| 批量批准 | `POST /ai/regression-cases/batch-review`（1–50 条）；页面多选草稿、一次确认，逐条返回 UPDATED/SKIPPED/FAILED | 仅管理员；仅 DRAFT 可批准，状态不符、重复编号或已删除条目单独说明，不影响其余项 |
| 单条兜底 | `create_case` 同样先脱敏再计算用例键并入库 | 单条与批量共用一套规则，避免两套口径 |
| 生产口径 | `scripts/report_regression_conversion.py`：最早 DOWN 反馈（无反馈则任务创建）→ `reviewed_at`，输出 p50/p90 与 24 小时比例 | 当前库 90 天查询 0 条 → `NO_PRODUCTION_SAMPLES`，不把空样本算成 0 小时 |

验证：回归用例与脱敏相关 32 项单测通过（含“候选→批量入库→批量批准→导出”链路）；合成基准 1 项、生产统计 3 项；前端 `vue-tsc --noEmit` 通过。
合成链路基准：[回归用例转化流水线基准](evaluation/regression-conversion-benchmark.md) 用 20 条合成差评与审批记录跑通
候选→入库→批准→导出，机器流水线约 31 ms（20 新建 / 18 批准 / 2 归档 / 18 导出）；
报告显式标注 `production_measured=false`，fixture 审批时间偏移不参与耗时计算，不能替代生产转化时长。
生产库实测：现有 3 条已批准用例均来自 `WORKER_UNAVAILABLE` 基础设施失败，报告默认排除后仍判
`NO_PRODUCTION_SAMPLES`（`excluded_infra=3`）；默认候选列表只剩 1 条语义失败（`MODEL_FORMAT_ERROR`），
只有显式 `include_infra` 才显示全部 5 条。因此“转化 ≤1 天”仍不能判定。
低成本补数方案：用真实失败任务/差评做小样本 pilot（当前库有 7 条失败任务、2 条草稿），批准后同时看
“反馈→批准”和“草稿→批准”两段；全过样本的 24h 超限率单侧 95% 上界为 `1-0.05^(1/n)`，
n=9 时约 28.3%，n=29 全过才约 9.8%——样本不足时只能报观测值与区间，不能宣称 90% 达标。
未做：生产样本人工时长（当前库无已批准样本）；前端只做了类型检查与代码走查，
未完成浏览器验收（本机 vitest 启动被沙箱 `spawn EPERM` 阻断）；
规则只覆盖可判定字段，产品、供应商名等业务实体仍依赖人工核对。

routing 14 轮补证已落地（未提交）：

| 变更 | 实现 | 判定口径 |
| --- | --- | --- |
| 长轮次采样 | `eval_harness.py --suite routing --repeat 14`，34 条 × 14 轮 = 476 次真实请求 | envelope `PASS`；34/34 `STABLE_PASS`，0 `UNSTABLE`，0 `STABLE_FAIL` |
| 污染处置 | 首轮 trial-3/9/10 成片 `INTENT_SERVICE_ERROR`，删除后 `--resume` 定向重跑 | 最终 0 基础设施轮次计入分母；此前两条 2/3 用例均 14/14 |
| 检测修复 | `evaluate_intent_routing.py` 失败行补 `run_meta.error.class`（复用 `error_policy.classify`） | harness 能自动识别并重跑路由侧基础设施失败；单测覆盖 |
| 证据 | [路由评测 14 轮稳定性证据](evaluation/routing-14-round-stability.md) | 记录模型、prompt 指纹、请求量、污染重跑与边界 |

business 3 条定向补证已落地（未提交）：

| 变更 | 实现 | 判定口径 |
| --- | --- | --- |
| 定向采样 | `evaluate_agent_business.py --cases B001 B032 B033 --repetitions 14 --workers 3` | 42/42 通过；新增 14/14，与原 3 轮 2/3 合并 16/17 `STABLE_PASS` |
| 范围控制 | 只补原三条 UNSTABLE，不重跑 120 条全量 | 不改变其他 business 场景的既有证据 |
| 证据 | [business 不稳定用例 14 轮定向补证](evaluation/business-unstable-14-round-retest.md) | 记录模型、命令、合并口径与边界 |

下一步（按顺序）：

1. 已完成：envelope 基线登记 + CI 切换——四份 `harness-<suite>.json` 已写入当前 prompt 版本目录，
   `--mode envelope` 自比 PASS；CI 改走 `--harness --repeat 3 --preflight --require-baseline --gate`，
   缺基线在采样前退出。未做：首轮 Actions 实跑（含限流处置）尚未发生。
2. 已完成：5 条 UNSTABLE 全部定向补证——business B001/B032/B033 各补 14 轮（42/42 通过，累计 16/17）；
   routing 两条整轮补到 14 轮（34/34，两条均 14/14）。证据见上述两份报告。
3. 已完成：P1 实验框架 `prompt_experiment.py`——配对 2×2 列联表、McNemar 精确检验、改善/退化清单，
   只读 envelope、不提供 promote；9 项单测覆盖改善、退化、无差异、跨模型阻断与无有效轮次。
4. 已完成：评测失败用例批量转回归用例——`--failed-only/--case-ids` + `--expected-mode auto` + 去重跳过 + `--dry-run`；
   真实业务报告 dry-run 得 12 条唯一候选、20 条重复跳过、0 条推导失败。
   已完成：差评/失败任务批量转用例——候选批量接口 + 服务端确定性脱敏 + 一次确认 + 管理员批量批准，单条提交同样兜底脱敏。
   已补合成链路基准（仅机器耗时）与生产统计脚本；当前生产库无样本，人工时长仍不能判定。未做：前端浏览器验收。
5. 已完成：P2 结果入库与趋势——`database/migrations/076_ai_eval_runs.sql`、`scripts/apply_migration.py`
   （PowerShell 无 `<` 重定向，统一用内置执行器）、`scripts/record_eval_run.py`（按 envelope 指纹幂等，
   逐用例写入 `ai_eval_case_results`）、`scripts/eval_trend.py`（月度稳定通过率）。
   迁移已应用：4 份 envelope、175 条用例入库，2026-11 稳定通过率 97.1%（170 STABLE_PASS / 5 UNSTABLE）。
   10 项单测覆盖幂等、跨月聚合、按套件过滤、CLI 与迁移语句拆分。

离线核对仍成立：用历史报告合成 envelope 后自比判 PASS，注入 3 轮全失败用例判 REGRESSION；
真实采样已验证四套件都能产出 envelope，且污染轮次被重跑后统计为 0 排除。

## 10 页面上下文路由、能力硬约束与浮窗提案闭环进展

已完成两阶段改造：第一阶段在保持 `ROUTING_PROMPT` 不变（`routing@1-5531c235`）下打通服务端上下文校验、Schema 与前端全链路；第二阶段经四套件对照实验受控升级至 `routing@1-752b1384__planner@1-2911a494`：

| 变更 | 实现 | 验证与边界 |
| --- | --- | --- |
| 路由页面上下文与兜底（`b8aa972`、`e1654db`） | `/api/v1/ai/route` 增加可选 `page_context` 权限校验与只读快照注入；`routing.understand` 自动绑定当前单据编号并执行能力清单与单据状态硬约束；`Understanding` 前置清理 `action_fields` 中的 `null` 占位键；`StrictJsonDecimal` 与 `PurchaseRequestActionItem` 修复 `strict=True` JSON 对 `Decimal`（`budget_amount` / `quantity` / 明细单价与数量）全拒的契约缺陷 | 后端路由/契约/动作单测通过；不改 Prompt 时标准 `routing` 34 条 × 3 轮 `34/34` 通过、9 场景 × 3 轮（`deepseek-v4.1-flash`）从 `3/27` 提至 `23/27`（`PC03` `0/3 → 2/3`） |
| 工作台与浮窗提案闭环（`0781891`、`f68b935`、`aa7a2ce`） | `routeAiRequestApi` 与 AI 工作台透传 `pageContext`；抽出共用 `action-proposal-plan.ts` 统一 6 类写操作校验与负载；详情浮窗 `page-copilot-drawer.vue` 接入 `/ai/route` 与 `<Modal>` + `<ActionProposalDetail>` 完成提案预览、修订、取消与确认执行；遮罩白名单防弹窗内点击误关抽屉；采购订单详情与采购申请详情抽屉/列表均接入 `chemicalops:proposal-executed` 自动刷新 | `vue-tsc --noEmit --skipLibCheck` 退出码 0；`vitest` 3 个文件 10 项通过；`http://localhost:3000` 浏览器实机验证 `QA-PO-20261004-03`（`ORDERED`）只读追溯与状态拦截，以及草稿采购申请 `PR20261025002124` “修改预算为 5500 元 → 生成提案 → `<ActionProposalDetail>` 点击确认执行（HTTP 200）→ 详情抽屉与列表行无整页刷新实时更新为 `5,500 CNY`”全链路 |
| 专项脚本沉淀（`9d7186c`） | 新增独立脚本 `scripts/evaluate_page_context_routing.py`（支持 `eval`/`compare`，不改 34 条基线题集）与单测 `tests/test_eval_page_context_routing.py` | 路由与专项评测单测 118 项通过，`--help` 退出码 0 |
| Harness 分片并行与 CI DAG（`3ebe8be`） | `evaluate_agent_business.py` 新增步长均衡分片（`--shard-index`/`--shard-count`）；`eval_harness.py` 支持本地并行分片（`--business-shards`）、跨套件并行（`--parallel-suites`）、单轮及 envelope 合并（`--merge-shards`）；`.github/workflows/agent-eval.yml` 拆分为 `preflight → fast-suites + 3×business-shard → gate` 矩阵并行 | `eval_harness` / `run_eval_suite` / 门禁相关 `pytest` 207 项通过；`--shard-index 1 --shard-count 3 --validate` 验证 40 条隔离样本构建；CI 工作流 YAML 解析通过；本机实测四套件 × 3 轮（`--business-shards 3 --workers 2 --parallel-suites`）总耗时约 29 分钟 56 秒（≤40 分钟 DoD 达标；GitHub Actions 云端实跑仍待首轮触发取证） |
| 路由 Prompt 受控升级与基线切换（`42ae7db`） | `ROUTING_PROMPT` 增加 `purchase_update.action_fields` 允许字段说明与 `budget_amount` 边界示例，明确 `context.page_context` 指代绑定与 `valid_write_purposes` 能力/状态拦截规则；更新 `tests/fixtures/prompt_hashes.json` 并通过 `eval_prompt_gate.py --promote-baseline` 登记新基线 `routing@1-752b1384__planner@1-2911a494` | 9 场景 × 3 轮页面上下文专项实测升至 **`27/27`**（`PC03`、`GD02`、`GD04` 均 3/3）；四套件 × 3 轮（`deepseek-v4.1-flash`）全过：`routing 34/34`、`tasks 16/16`、`business 120/120`、`prod 5/5`（`175/175 STABLE_PASS`、0 失败、0 基础设施错误）；`prompt_experiment.py` 对旧基线 `routing@1-5531c235` 四套件均为 `0` 退化；`eval_prompt_gate.py --mode envelope --fail-on-regression` 判定 `PASS`；`record_eval_run.py` 入库后 `eval_trend.py` 显示 2026-11 累计 8 次运行 `345/350` 稳定通过（`98.6%`）；提示词/路由/门禁相关 `pytest` 209 项通过 |
| 助手面板叠放层级修复（`85bc9c6`） | `page-copilot-drawer.vue` 设置抽屉 `:z-index="2050"`（高于业务详情抽屉 `1000`，低于浮动入口 `2100`），并为作用域下拉 `<Dropdown>` 与提案确认 `<Modal>` 统一设置 `:z-index="2150"` / `root: { zIndex: 2150 }` | `vue-tsc --noEmit` 退出码 0，`vitest` `floating-panel-state.test.ts` 4/4 通过；浏览器实测因 Vite 开发编译耗时被中断，详情抽屉叠放与多详情页动作流待复验 |
| M3 → T3 自动归集与实验闭环（`7cbd0b9`） | 新增 `rsi_cycle.py` 与 `scripts/run_rsi_cycle.py`，并在 `run_scheduler.py` `run_once()` 挂载异常隔离的自动候选归集：管理员权限校验 + 确定性脱敏后幂等生成 `DRAFT` 回归用例；按 `error_policy.failure_stage` 与 `AIFeedback.reason_code` 聚合至 `ROUTING_PROMPT` / `AGENT_TOOL_CONTRACTS` / `PLANNER_PROMPT` 只读改进提案（`auto_applied=False`）；支持编排 `eval_harness` + `prompt_experiment` + `eval_prompt_gate` 出统一 JSON/Markdown 报告且禁止 `--promote-baseline` | 离线 `pytest` 相关套件 `183 passed`（含 `tests/test_rsi_cycle.py`）；本地库 `run_rsi_cycle.py --dry-run --days 30` 联合 `routing@1-752b1384__planner@1-2911a494` 自比验证通过（`DRY_RUN`、`INCONCLUSIVE`、`PASS`）；当前库 30 天内反馈 `0` 条，`NO_PRODUCTION_SAMPLES` 待真实反馈积累 |

后续任务顺序：

1. **恢复浏览器实机验收（叠放层级 + 多详情页写操作提案）**：在预热后的 `http://localhost:3000` 验证详情抽屉与 `page-copilot-drawer` / `<Modal>` 叠放层级，并抽测草稿采购订单提交、已审批采购申请生成询价草稿等动作提案闭环。
2. **完成 GitHub Actions 首轮实跑取证**：推送远端并触发 `.github/workflows/agent-eval.yml`，验证云端 `fast-suites` + 3 路 `business-shard` 并行耗时与模型限流表现。
3. **补充生产反馈审核样本**：基于真实业务使用中的差评与有效失败任务，经后台审阅批准入 `prod-regression/cases.json`，以实测回归转化时长（目标 ≤1 天，解除 `NO_PRODUCTION_SAMPLES`）。
