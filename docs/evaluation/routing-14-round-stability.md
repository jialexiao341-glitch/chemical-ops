# 路由评测 14 轮稳定性证据

## 口径

- 采集时间：2026-11-12
- 模型：`deepseek-v4.1-flash`（MaxApi），真实 HTTP 调用
- Prompt：`routing@1-5531c235`（`prompt_sha256` = `5531c235…`）
- 命令：`python scripts/eval_harness.py --suite routing --repeat 14`
- 规模：34 条合成路由用例 × 14 轮 = 476 次请求；envelope 判定 `PASS`
- 判定：`eval_stability.classify`（Wilson 95%，下界 ≥0.7 判 STABLE_PASS）

## 结果

| 判定 | 用例数 |
| --- | ---: |
| STABLE_PASS | 34 |
| UNSTABLE | 0 |
| STABLE_FAIL | 0 |
| 计入分母的基础设施轮次 | 0 |

14 轮全部通过（34/34）；此前 3 轮基线中的两条 2/3 用例本轮均为 14/14：

- 先查乙醇库存，然后创建采购申请
- 查乙醇库存，再查甲醇库存，两项各看前5条

## 采集过程中的污染与重跑

首轮 14 批次中 trial-3、trial-9、trial-10 出现成片 `INTENT_SERVICE_ERROR`（模型服务抖动），
导致 envelope 一度判 `FAILURES`、34 条用例全部被至少一轮污染覆盖。删除这三份 trial 后
以 `--resume` 定向重跑，最终 14 份 trial 均无失败。

同时修正评测器：`scripts/evaluate_intent_routing.py` 的失败行补充 `run_meta.error.class`
（复用 `error_policy.classify`），使 `eval_harness` 能识别路由侧基础设施失败并在 resume 时自动重跑，
避免把模型抖动固化成实现失败。`tests/test_ai_evaluation.py` 增加对应断言。

## 边界

- 合成语义路由样本，只验证路由类别、任务集合与执行契约；不验证工具执行、检索质量或生产业务效果。
- 采集时工作区包含未提交改动，envelope 的 `code_revision` 为空；结论对应 prompt 指纹与模型，不对应某个已提交版本。
- 单轮耗时约 100–180 秒，14 轮属于定向补证，不是日常门禁默认轮次。