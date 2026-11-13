# 回归用例转化流水线基准（合成样本）

> 数据来源是仓库内合成 fixture，**不是生产差评，也不是真实人工审批记录**。
> 本报告只测应用侧机器耗时，不能用于宣称“转化 ≤1 天”。

## 样本与范围

- 合成差评样本：20 条；时间窗口 7 天
- fixture：`docs/evaluation/regression-conversion-fixtures/feedback-samples.json`、`docs/evaluation/regression-conversion-fixtures/approval-records.json`
- 运行环境：SQLite 内存库，进程内调用真实服务函数
- 复现：`python scripts/measure_regression_conversion.py`（`--json` 输出原始结果）

## 数量结果

| 候选 | 新建 | 复用 | 跳过 | 失败 | 批准 | 归档 | 导出 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 20 | 0 | 0 | 0 | 18 | 2 | 18 |

## 机器耗时（毫秒）

| 阶段 | 毫秒 |
| --- | ---: |
| 候选生成 | 5.54 |
| 批量脱敏入库 | 14.99 |
| 批量批准 | 5.05 |
| 批量归档 | 0.65 |
| 导出 | 4.69 |
| 流水线合计（不含 fixture 建库） | 30.92 |

单次进程内执行的毫秒级数值会随机器负载波动；本文件记录一次实际运行结果，不构成性能承诺。

## 脱敏命中（合成样本）

- `mobile ×2`、`contact ×3`、`email ×2`、`id_card ×2`、`bank_card ×1`、`ip ×1`、`company ×1`、`landline ×1`

## 边界

- SQLite 内存库与本地进程内调用，不代表生产数据库、网络和并发开销。
- 审批由脚本以管理员身份代执行，不是真实人工审批记录；fixture 中的审批时间偏移不参与任何耗时计算。
- 合成问题不含真实客户信息；不能据此宣称生产转化 ≤1 天。

## 生产口径如何补

1. 用真实任务的 `created_at`（首次反馈）与管理员 `reviewed_at` 计算人工转化时长。
2. 只统计 `ai_regression_cases.status = 'APPROVED'` 且 `reviewed_at` 非空的记录。
3. 按批次记录候选生成时间、批准时间和导出时间，避免用 fixture 时间偏移代替。

## 相关文件

- 合成差评：[feedback-samples.json](regression-conversion-fixtures/feedback-samples.json)
- 合成审批：[approval-records.json](regression-conversion-fixtures/approval-records.json)
- 测量脚本：[measure_regression_conversion.py](../../scripts/measure_regression_conversion.py)