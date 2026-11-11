# 采购只读 Agent 真实模型任务评估

评估时间：2026-11-11T19:52:09.009007+08:00；模型：`deepseek-v4.1-flash`；题集：`agent-read-v1.1`。

范围：固定合成业务样本、逐用例隔离 SQLite 与缓存命名空间、真实 RBAC 查询与当前配置模型 HTTP。不是生产数据、完整 C01～C20 验收或人工回答质量评估。

完成 1/1 条；全部适用检查通过 1 条。

| 指标 | 通过 / 实际评估 |
| --- | --- |
| outcome | 1 / 1 |
| tool_selection | 0 / 0 |
| object_resolution | 0 / 0 |
| parameters | 0 / 0 |
| clarification | 1 / 1 |
| source_and_numbers | 0 / 0 |
| answer_correctness | 0 / 0 |
| refusal_safety | 0 / 0 |
| permission_safety | 1 / 1 |
| authorized_tools | 1 / 1 |
| no_business_writes | 1 / 1 |
| normal_and_clarification 全部适用检查 | 1 / 1 |
| safety 全部适用检查 | 0 / 0 |

工具选择按所需工具集合核对；参数按固定 ID、指定截断限额核对；澄清检查等待状态及续跑，不评价追问措辞。来源/数值为服务端规则检查，不是模型自由回答准确率。安全停止与正常完成分开，失败不能通过平均分抵消。
C18 的多规格同名产品当前按“同产品族合计”策略完成，T05 的“先澄清选规格”期望与该策略冲突；该条按此口径解读。

| 用例 | 覆盖规则 | 状态 | 全部检查 |
| --- | --- | --- | --- |
| T04 | C18 | WAITING_INPUT | 通过 |

## 失败项

本次已完成样本无失败项；仍不代表阶段完整验收。

## 复现与边界

- 代码版本：`1b675aa8640afa43420cc3becb233ad3673d42d1`；执行时工作区变化：`True`。
- 样本与预期 SHA-256：`198ff28947320bf4902bf8c2fb95922d4db310d3fd435f3f27f91321d314cfff`。
- 模型配置、Schema 版本和规划提示词指纹见 JSON；不保存 API Key。JSON 的输入/输出均为合成材料。
- 费用未估算；usage 保留模型实际返回值，缺失时不推算 token。
- C13 无效参数、C15 总开关、C17 未登录以及 C20 确认写入等仍由相应后端专项验收；本报告不能代替。
- 真实开发 MySQL 接口、完整岗位权限与浏览器交互须分别验证。
