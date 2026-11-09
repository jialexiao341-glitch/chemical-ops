# Prompt 版本评测基线

基线目录按当前路由与规划提示词版本命名：

```text
routing@<version>-<hash>__planner@<version>-<hash>/
  intent_routing.json
  agent_tasks.json
  agent_business.json
  manifest.json
```

门禁脚本是 `scripts/eval_prompt_gate.py`。缺少当前版本目录时直接失败，禁止用旧版本基线冒充新基线。

## 首版基线

- 模型：`deepseek-flash`
- 采集：2026-11-09，每个场景 1 次运行
- 目录：`routing@1-849ce802__planner@1-fc37f6a3`

| 报告 | 通过 / 总数 | 通过率 |
| --- | ---: | ---: |
| 语义路由 | 29 / 34 | 85.3% |
| Agent 只读任务 | 13 / 16 | 81.3% |
| 业务场景 | 88 / 120 | 73.3% |

这是**回归参照**，不是质量达标证明。首版基线保留了当前失败项，用于后续变更捕获 PASS→FAIL；
真实发布前应复核失败原因，并至少用 3 次重复运行确认稳定性。

当前失败集中：

- 路由：部分多子问题被识别为 `query` 而非 `batch`，或过度澄清为 `clarify`。
- Agent 任务：T05 未按预期先澄清、T14/T15 过度澄清或未完成。
- 业务场景：`combined` 20 条、`clarification` 10 条、`quotes` 2 条；以过度澄清（21 条 `WAITING_INPUT`）为主。

登记或更新基线：

```powershell
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --candidate-dir docs/evaluation/candidate
.venv/Scripts/python.exe scripts/eval_prompt_gate.py --promote-baseline
```

覆盖已有基线需 `--force`。候选报告目录 `docs/evaluation/candidate/` 是运行产物，是否提交由维护者决定；
基线目录应在审阅后提交，供 CI 与本地门禁复用。