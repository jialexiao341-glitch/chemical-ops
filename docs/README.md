# 文档索引

仅维护当前有效说明与未完成建设计划；已完成阶段的历史计划与验收记录不再单独保留，原始数据与固定题集见 `evaluation/`。

## 项目与运行

- [项目简介与业务流程](项目简介与业务流程.md)
- [项目介绍与成果（STAR）](项目介绍与成果（STAR）.md)
- [运行、体验与测试指南](运行体验与测试指南.md)：启动、测试与开发数据维护边界。
- [部署与数据库恢复指南](部署与数据库恢复指南.md)
- [前端构建环境与共享界面规则](build-notes/前端构建环境说明.md)
- [数据库任务队列运行说明](数据库任务队列运行说明.md)
- [Agent 只读任务运行说明](Agent只读任务运行说明.md)
- [交期催办门户协同运行说明](交期催办门户协同运行说明.md)

## 当前能力与配置

- [Redis 缓存与限流](Redis接入与验证.md)
- [LLM Gateway 配置与兼容矩阵](LLM-Gateway兼容矩阵.md)
- [可观测性运行说明](后端可观测性运行说明.md)
- [告警通知与处置](可观测性告警处置说明.md)
- [数据库设计说明](数据库设计说明.md)、[接口文档](接口文档.md)：接口以运行时 OpenAPI 为准，表结构以迁移为准。
- [角色职责与三级权限矩阵](角色职责与三级权限矩阵.md)
- [用户注册与供应商身份管理](用户注册与供应商身份管理.md)
- [采购 Agent 业务规则与用例](Agent采购MVP业务规则与验收用例.md)
- [模拟发票样本](invoice-samples/README.md)、[质量报告样本](quality-reports/README.md)

## Agent 能力与评测

- [Agent 能力与 RSI 成熟度分析](Agent能力与RSI成熟度分析.md)：只读/写入/评测/RSI 现状与路线。
- [业务评测运行说明](evaluation/业务场景与任务可靠性评测运行说明.md)：四套件、envelope 门禁、变体实验与入库。
- [四套件三轮稳定性评估](evaluation/stability-all-r3.md)
- [不稳定用例定向复跑](evaluation/stability-targeted-rerun.md)
- [评测文件说明](evaluation/评测文件说明.md)：固定题集、原始证据与历史指标出处。
- [报价文件解析专项评测报告](evaluation/报价文件解析专项评测报告.md)、[缺口修复复测](evaluation/报价文件解析缺口修复复测.md)
- [浏览器验收：AI 质量与回归候选](evaluation/浏览器验收-AI质量与回归候选.md)

## 后续建设

- [企业级 Agent 功能蓝图与业务 AI 打通方案](企业级Agent功能蓝图与业务AI打通方案.md)
- [采购 Agent 建设路线图与多智能体方案](采购Agent建设路线图与多智能体方案.md)
- [企业级改造方案](ChemicalOps-企业级改造方案.md)：目标边界与放行标准。
- [改造任务清单](ChemicalOps-改造任务清单.md)

## 证据与素材

- `evaluation/`：固定题集、原始证据与稳定性报告；`evaluation/candidate/` 为本地运行产物。
- `evidence/`：JSON 与截图；`ui-reference/`：界面及品牌素材。