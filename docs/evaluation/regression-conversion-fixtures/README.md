# 回归用例转化 fixture

本目录只放**合成样本**，用于验证回归用例批量脱敏、批准、导出链路与机器耗时。

- `feedback-samples.json`：20 条合成差评任务，问题文本包含手机号、邮箱、身份证、银行卡、IP、联系人/单位名称等模式，用于覆盖确定性脱敏。
- `approval-records.json`：对应的合成审批记录（18 条批准、2 条归档），`reviewed_offset_minutes` 只是流程字段样例。

**重要边界**

1. 这些不是生产差评，不含真实客户、订单或人员信息。
2. 审批记录由脚本代执行，不是真实管理员操作记录；时间偏移不得用于计算“转化 ≤1 天”。
3. 生产转化时长必须用真实任务的 `created_at` 与 `ai_regression_cases.reviewed_at` 统计。

## 复现

```bash
python scripts/measure_regression_conversion.py            # Markdown 结果
python scripts/measure_regression_conversion.py --json     # 原始 JSON
python scripts/measure_regression_conversion.py --out docs/evaluation/regression-conversion-benchmark.json
```

脚本使用内存 SQLite，不读取 `.env`、不调用模型、不写业务库。

## 换成生产口径

1. 导出真实 `ai_agent_tasks`、`ai_feedback`（`rating=DOWN`）与 `ai_regression_cases` 的匿名化记录。
2. 按本目录 JSON 结构替换 `samples` 与 `records`，并把 `kind` 改为生产导出标识。
3. 用 `created_at`、`reviewed_at` 计算人工时长；不要使用 fixture 的 `reviewed_offset_minutes`。
4. 单独标注样本量、时间窗口、排除项（如重复反馈、已归档任务）。