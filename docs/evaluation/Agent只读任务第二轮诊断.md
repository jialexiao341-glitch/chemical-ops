# 采购只读 Agent 真实模型任务评估

评估时间：2026-10-03T11:18:36.245473+08:00；模型：`deepseek-flash`；题集：`agent-read-v1`。

范围：固定合成业务样本、隔离 SQLite、真实 RBAC 查询与当前配置模型 HTTP。不是生产数据、完整 C01～C20 验收或人工回答质量评估。

完成 16/16 条；全部适用检查通过 14 条。

| 指标 | 通过 / 实际评估 |
| --- | --- |
| outcome | 15 / 16 |
| tool_selection | 10 / 10 |
| parameters | 9 / 10 |
| clarification | 3 / 3 |
| source_and_numbers | 12 / 12 |
| authorized_tools | 16 / 16 |
| no_business_writes | 16 / 16 |

工具选择按所需工具集合核对；参数按固定 ID、指定截断限额核对；澄清检查等待状态及续跑，不评价追问措辞。来源/数值为服务端规则检查，不是模型自由回答准确率。安全停止与正常完成分开，失败不能通过平均分抵消。

| 用例 | 覆盖规则 | 状态 | 全部检查 |
| --- | --- | --- | --- |
| T01 | C01, C02, C03, C04 | SUCCEEDED | 失败 |
| T02 | C07, C08, C09, C10, C11 | SUCCEEDED | 通过 |
| T03 | C19 | SUCCEEDED | 通过 |
| T04 | C18 | WAITING_INPUT | 通过 |
| T05 | C18 | SUCCEEDED | 通过 |
| T06 | C18, C19 | SUCCEEDED | 通过 |
| T07 | C06 | REJECTED | 通过 |
| T08 | C06 | SUCCEEDED | 通过 |
| T09 | C05 | WAITING_INPUT | 通过 |
| T10 | C12 | SUCCEEDED | 通过 |
| T11 | C14, C16 | WAITING_INPUT | 通过 |
| T12 | C13, C14 | WAITING_INPUT | 通过 |
| T13 | C17 | SUCCEEDED | 通过 |
| T14 | C17 | WAITING_INPUT | 失败 |
| T15 | C10, C19 | SUCCEEDED | 通过 |
| T16 | C16 | SUCCEEDED | 通过 |

## 失败项

- T01：parameters；完整输入、模型 JSON、工具证据及续跑结果见同名 JSON。
- T14：outcome；完整输入、模型 JSON、工具证据及续跑结果见同名 JSON。

## 复现与边界

- 代码版本：`21cd92a7a74a7fc90f0c839442451db9d2c2692e`；执行时工作区变化：`True`。
- 样本与预期 SHA-256：`3aa490d726d6c190e376251966b1734200a82aa99cfbd07c8add91c9c3ea2dc2`。
- 模型配置、Schema 版本和规划提示词指纹见 JSON；不保存 API Key。JSON 的输入/输出均为合成材料。
- 费用未估算；usage 保留模型实际返回值，缺失时不推算 token。
- C13 无效参数、C15 总开关、C17 未登录以及 C20 确认写入等仍由相应后端专项验收；本报告不能代替。
- 真实开发 MySQL 接口、完整岗位权限与浏览器交互须分别验证。

> 历史诊断保留：首轮对仓储角色的数值预期有误，第二轮已修正；v1.1 将 T14 改为明确产品名称，题集指纹不同。不得按轮次比例推算质量提升。最终报告见 [真实模型评估](Agent只读任务真实模型评估.md)。
