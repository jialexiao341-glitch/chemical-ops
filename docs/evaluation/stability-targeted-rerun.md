# 不稳定用例定向复跑

> 采集：2026-11-12 12:44–12:53（Asia/Shanghai），模型 `deepseek-v4.1-flash`（MaxApi）。
> 口径：原 3 轮 trial 与新增 7 轮合并为 10 轮，有效轮次排除 `TRANSIENT_INFRA`；
> Wilson 95% 下界 ≥0.7 才判 `STABLE_PASS`，少于 5 轮时按全过/全败简化判定。

## 结果

| 用例 | 原 3 轮 | 补 7 轮 | 合计 | Wilson 95% | 判定 |
| --- | --- | --- | ---: | --- | --- |
| B001 | 失败 / 通过 / 通过 | 7/7 通过 | 9/10 | [0.596, 0.982] | UNSTABLE |
| B032 | 通过 / 通过 / 失败 | 7/7 通过 | 9/10 | [0.596, 0.982] | UNSTABLE |
| B033 | 通过 / 通过 / 失败 | 7/7 通过 | 9/10 | [0.596, 0.982] | UNSTABLE |

21 次复跑全部 `SUCCEEDED`，0 条基础设施失败。三个用例在 3 轮阶段各失败 1 次，7 次复跑均未复现。

## 结论

- 三次失败更像采样或工具路径波动，没有稳定复现；不据此判实现回归。
- 但 9/10 的 Wilson 下界只有 0.596，仍低于 0.7，判定保持 `UNSTABLE`。按现行口径，
  出现一次失败后需要约 14–15 轮连续全过（14/15 的下界约 0.70）才能改判 `STABLE_PASS`；10 轮不够。
- 处置：作为 flaky 观察项保留，不计回归；若同一检查项再次失败，再按用例定向复跑定位。
  检查项分别为 B001 `final_answer_facts/object_location/outcome/tool_selection`、
  B032 `final_answer_facts/outcome/tool_selection`、
  B033 `clarification/final_answer_facts/object_location/outcome/tool_selection`。

## 未复跑的用例

routing 的两条 UNSTABLE（`先查乙醇库存，然后创建采购申请`、`查乙醇库存，再查甲醇库存，两项各看前5条`）
不在本次范围：`evaluate_intent_routing.py` 只支持整轮 `--repeats`，没有单例筛选；
复跑需整轮 34 条 × 7 轮，与“暂不跑全量”的约定冲突，保持 `UNSTABLE`。
若需要翻案，需要整轮补跑到 14–15 轮全过，成本明显高于本次定向复跑；本次不执行，保持 `UNSTABLE`。