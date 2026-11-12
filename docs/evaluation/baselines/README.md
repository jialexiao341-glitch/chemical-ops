# Prompt 版本评测基线

基线目录按当前路由与规划提示词版本命名：

```text
routing@<version>-<hash>__planner@<version>-<hash>/
  intent_routing.json
  agent_tasks.json
  agent_business.json
  prod_regression.json
  harness-routing.json   # envelope 口径，迁移后必填
  harness-tasks.json
  harness-business.json
  harness-prod.json
  manifest.json
```

门禁脚本是 `scripts/eval_prompt_gate.py`。缺少当前版本目录时直接失败，禁止用旧版本基线冒充新基线。
`manifest.json` 的 `report_versions` 记录每份报告实际使用的提示词版本；
`carried_forward` 列出未随当前版本重跑、从上一版本延用的报告。延用报告必须在门禁和发布说明中保留可见标记。
`manifest.envelopes` 与 `manifest.envelope_meta` 记录 envelope 文件名、模型、代码版本、提示词指纹与轮次，
供 `--mode envelope` 校验“是否在同一模型、同一代码版本下采样”。

## 当前基线

- 提示词：`routing@1-5531c235__planner@1-2911a494`
- 模型：`MaxApi` / `deepseek-v4.1-flash`（思考强度 high）。2026-11-11 四个套件全部重跑，`manifest.collected_model` 已记录。
- 目录：`routing@1-5531c235__planner@1-2911a494`
- 采集：2026-11-11。业务 120×3、Agent 任务 16、生产差评 5、路由 34；已记录用量约 190 万 tokens（业务 1,809,117 + 任务 93,705；路由与生产差评报告未记录 usage）。
- envelope 基线：2026-11-12 四套件各 3 轮（`harness-<suite>.json`），模型与提示词同上；
  结果 170 STABLE_PASS / 5 UNSTABLE / 0 STABLE_FAIL，0 轮基础设施排除（污染轮次已重跑）。
  逐用例表见 [四套件三轮稳定性评估](../评测运行与稳定性.md)，`manifest.envelopes`/`envelope_meta` 已登记；
  `--mode envelope` 自比判 PASS。这是在原始报告之外并列登记的第二套口径，原始报告未被覆盖。

| 报告 | 通过 / 总数 | 通过率 | 说明 |
| --- | ---: | ---: | --- |
| 语义路由 | 34 / 34 | 100.0% | 首轮 30/34 为模型偶发非法 JSON，重试后 34/34；首轮报告为本地运行产物，已清理，未随版本库保留 |
| Agent 只读任务 | 16 / 16 | 100.0% | T05 FAIL→PASS，0 回归 |
| 业务场景 | 120 / 120 | 100.0% | 3 次重复全部通过才算；B072 三次由修复后定向重跑替换，其余 357 次为原全量批次 |
| 生产差评回归 | 5 / 5 | 100.0% | 当前 `planner@1-2911a494` |

与上一基线 `routing@1-5531c235__planner@1-90970018` 对比：

| 报告 | 上一基线 | 当前 | 变化 | 回归 |
| --- | ---: | ---: | ---: | --- |
| 语义路由 | 34 / 34（100.0%） | 34 / 34（100.0%） | 0 | 0 |
| Agent 只读任务 | 15 / 16（93.8%） | 16 / 16（100.0%） | +1（T05） | 0 |
| 业务场景 | 108 / 120（90.0%） | 120 / 120（100.0%） | +12（10 条 clarification、B039、B103、B072） | 0 |
| 生产差评回归 | 5 / 5（100.0%） | 5 / 5（100.0%） | 0 | 0 |

这是**回归参照**，不是质量达标证明。基线保留当前失败项，用于后续变更捕获 PASS→FAIL。

策略变更（2026-11-11）：同名不同规格不再合计库存，只有同一 `product_id`（同规格）跨仓库才合计，
多规格先澄清。T05 与 10 条 `clarification` 业务用例（B009、B021、B033、B045、B057、B069、B081、B093、B105、B117）均已转通过。

当前失败与偶发：

- 路由：全量无失败；首轮 4 条 `INTENT_SCHEMA_ERROR`（模型偶发非法 JSON/布尔字段），重试重跑 34/34。
- Agent 任务：无。
- 业务场景：B072 trial=2 原为 `INTENT_SCHEMA_ERROR`。已为 `Slots.aggregate_products` 增加显式布尔兼容，
  定向重跑 B072 三次全部通过，并用这三次结果替换基线中的 B072 行；其余 357 次运行保持原全量批次。
  原始批次为本地运行产物，未随版本库保留（已清理）；替换说明写入报告 `evidence_note`。
- 生产差评回归：无。

模型偶发的结构化输出错误会以 `INTENT_SCHEMA_ERROR` 计入失败，属 harness 稳定性问题，不应直接判定为业务能力回归；
排查时应先看 `evaluation_error_type` 和失败轮次，再用定向重跑确认。

基线的进度：`routing@1-5531c235__planner@1-2911a494` 已同时登记四份原始报告与四份 `harness-<suite>.json`
envelope（2026-11-12，四套件各 3 轮），`--mode envelope` 自比判 PASS，`--mode reports` 仍可读取原始报告。
剩余迁移动作只有 CI：把 `.github/workflows/agent-eval.yml` 的 `run_eval_suite.py --gate` 换成
`--harness --repeat 3 --gate`。切换前 CI 继续按原始报告口径运行；两种口径现在读的是同一 prompt 版本目录，
不会互相覆盖（envelope 与原始报告文件名不同，`manifest` 同时记录两套元数据）。

## 首版基线

- 模型：`deepseek-flash`
- 采集：2026-11-09，每个场景 1 次运行
- 目录：`routing@1-849ce802__planner@1-fc37f6a3`

| 报告 | 通过 / 总数 | 通过率 |
| --- | ---: | ---: |
| 语义路由 | 29 / 34 | 85.3% |
| Agent 只读任务 | 13 / 16 | 81.3% |
| 业务场景 | 88 / 120 | 73.3% |

首版失败分布：路由的多子问题拆分/过度澄清；Agent 任务的 T05、T14、T15；业务场景 `combined` 20 条、
`clarification` 10 条、`quotes` 2 条，以过度澄清（21 条 `WAITING_INPUT`）为主。

## 登记或更新基线

```powershell
# 对比当前版本基线；有回归或安全失败时返回 2
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --candidate-dir docs/evaluation/candidate --fail-on-regression

# 多轮采样后按 envelope 判定；envelope 默认在 candidate/envelopes/
.venv/Scripts/python.exe scripts/eval_harness.py --suite all \
  --out-dir docs/evaluation/candidate/envelopes --repeat 3
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --mode envelope --fail-on-regression

# 人工审阅候选后登记为新基线（同时登记 envelope 与其 meta）；覆盖已有基线需 --force
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --promote-baseline
```

登记时若报告未随当前提示词版本重跑，命令会打印延用报告及其版本，并写入 `manifest.carried_forward`。
候选报告目录 `docs/evaluation/candidate/` 是运行产物，是否提交由维护者决定；
基线目录应在审阅后提交，供 CI 与本地门禁复用。envelope 基线未登记时 `--mode envelope` 会直接报缺基线，
不会回退到原始报告口径。