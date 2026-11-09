# Prompt 版本评测基线

基线目录按当前路由与规划提示词版本命名：

```text
routing@<version>-<hash>__planner@<version>-<hash>/
  intent_routing.json
  agent_tasks.json
  agent_business.json
  prod_regression.json
  manifest.json
```

门禁脚本是 `scripts/eval_prompt_gate.py`。缺少当前版本目录时直接失败，禁止用旧版本基线冒充新基线。
`manifest.json` 的 `report_versions` 记录每份报告实际使用的提示词版本；
`carried_forward` 列出未随当前版本重跑、从上一版本延用的报告。延用报告必须在门禁和发布说明中保留可见标记。

## 当前基线

- 提示词：`routing@1-5531c235__planner@1-90970018`
- 模型：`deepseek-flash`
- 目录：`routing@1-5531c235__planner@1-90970018`
- 路由、Agent 任务、生产差评：2026-11-09 重跑
- 业务场景：2026-11-09 的 3 次重复报告；生成时为 `routing@1-3cbf7acf`，规划提示词与当前一致。本次只补跑路由与生产差评，业务报告延用，`manifest.carried_forward` 已记录。

| 报告 | 通过 / 总数 | 通过率 | 说明 |
| --- | ---: | ---: | --- |
| 语义路由 | 34 / 34 | 100.0% | 当前 `routing@1-5531c235` |
| Agent 只读任务 | 15 / 16 | 93.8% | 当前 `routing@1-5531c235`；T05 失败 |
| 业务场景 | 108 / 120 | 90.0% | 3 次重复全部通过才算；逐次完成率 268 / 300（89.3%） |
| 生产差评回归 | 5 / 5 | 100.0% | 当前 `routing@1-5531c235` |

与首版基线 `routing@1-849ce802__planner@1-fc37f6a3` 对比：

| 报告 | 首版 | 当前 | 变化 | 回归 |
| --- | ---: | ---: | ---: | --- |
| 语义路由 | 29 / 34（85.3%） | 34 / 34（100.0%） | +5 | 0 |
| Agent 只读任务 | 13 / 16（81.3%） | 15 / 16（93.8%） | +2 | 0 |
| 业务场景 | 88 / 120（73.3%） | 108 / 120（90.0%） | +20 | 1（B039，1 / 3 次） |
| 生产差评回归 | 未采集 | 5 / 5（100.0%） | 新增 | 0 |

这是**回归参照**，不是质量达标证明。基线保留当前失败项，用于后续变更捕获 PASS→FAIL；
真实发布前应复核失败原因，并至少用 3 次重复运行确认稳定性。

当前失败集中：

- 路由：无。
- Agent 任务：T05 未按“先澄清多规格”完成。现行策略对同名或已登记为同一有效化学品的产品族直接合计库存，
  该用例期望与策略冲突；首版基线同样失败，不是本轮新增回归。
- 业务场景：10 条 `clarification` 确定性失败（B009、B021、B033、B045、B057、B069、B081、B093、B105、B117），
  原因与 T05 相同，首版基线同样失败。另有 2 条稳定性失败：B039（`inventory`，3 次中第 3 次转为单位筛选澄清）、
  B103（`combined`，3 次中第 2 次失败）；按“3 次全部通过”口径计为失败，不是确定性回归。
- 生产差评回归：无。

业务报告延用的原因：用户决定不再重跑 120×3 业务评测，仅补跑路由与生产差评。
该报告的路由版本为 `routing@1-3cbf7acf`，与当前版本不同；在作为发布证据前，应重跑完整业务套件并登记新基线。

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

# 人工审阅候选后登记为新基线；覆盖已有基线需 --force
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --promote-baseline
```

登记时若报告未随当前提示词版本重跑，命令会打印延用报告及其版本，并写入 `manifest.carried_forward`。
候选报告目录 `docs/evaluation/candidate/` 是运行产物，是否提交由维护者决定；
基线目录应在审阅后提交，供 CI 与本地门禁复用。