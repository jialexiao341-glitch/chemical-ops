# business 不稳定用例 14 轮定向补证

## 口径

- 采集时间：2026-11-12
- 模型：`deepseek-v4.1-flash`（MaxApi）
- 用例：`B001`、`B032`、`B033`（原 3 轮 envelope 均为 2/3 `UNSTABLE`）
- 命令：`python scripts/evaluate_agent_business.py --cases B001 B032 B033 --repetitions 14 --workers 3`
- 规模：3 条 × 14 轮 = 42 次真实模型请求；新批次 42/42 通过

## 结果

与原 3 轮 envelope 合并（2/3 + 14/14）：

| 用例 | 基线 | 新增 | 累计 | 判定 |
| --- | ---: | ---: | ---: | --- |
| B001 | 2/3 | 14/14 | 16/17 | STABLE_PASS |
| B032 | 2/3 | 14/14 | 16/17 | STABLE_PASS |
| B033 | 2/3 | 14/14 | 16/17 | STABLE_PASS |

Wilson 95% 下界约 0.78，均达到 `STABLE_PASS` 阈值 0.7。

## 边界

- 只补了原先不稳定的三条用例，不重跑全部 120 条场景。
- 合并的是同一 prompt 指纹与同一模型下的两批证据；跨 prompt/模型不能这样合并。
- 定向报告与 raw 轨迹在临时目录，未入库为基线；如需登记新基线仍走人工审阅与 `--promote-baseline`。
- 结果只验证这三条场景的稳定性，不证明全部 business 场景或生产业务效果。