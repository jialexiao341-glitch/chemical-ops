# ChemicalOps UI 重设计调研与参考方案

> 本文记录本次设计调研、视觉方向和参考图。参考图用于后续前端重构，不直接复制第三方品牌、Logo 或页面。

## 一、调研结论

### 1. SAP Fiori：面向角色和任务组织企业业务

SAP Fiori 强调 role-based、adaptive、simple、coherent、delightful 五个原则，并通过角色化入口、概览页和业务对象之间的联动减少传统 ERP 的复杂感。[SAP Fiori Concept and Design](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/22bbe89ef68b4d0e98d05f0d56a7f6c8/85f167b1da3d46d98e26cf4cac4430f8.html)

对 ChemicalOps 的启发：

- 首页优先展示当前角色最需要处理的采购、到货、库存和质量任务。
- 概览卡片必须能够下钻到业务列表或详情抽屉。
- 复杂流程用阶段、状态和待办表达，不把所有字段堆在首页。

### 2. Microsoft Fluent：留白、栅格和响应式节奏

Fluent 2 使用 4px 基础间距体系，强调通过间距表达组件关系，并推荐流式响应布局和 12 列栅格。[Fluent 2 Layout](https://fluent2.microsoft.design/layout)

对 ChemicalOps 的启发：

- 全局采用 4px spacing tokens，桌面端使用 12 列内容栅格。
- 页面保留大块呼吸空间，避免当前界面中边框、按钮和卡片过密。
- 移动和窄窗口下保留单一内容流，侧栏和详情面板可折叠。

### 3. Fluent Responsible AI：AI 必须可识别、可解释、可恢复

Fluent 的 Responsible AI 指南建议明确 AI 身份、能力边界、错误原因、后续操作和记忆保存范围，并用可展开的 reasoning panel 解释结果来源。[Fluent Responsible AI](https://fluent2.microsoft.design/responsible-AI)

对 ChemicalOps 的启发：

- AI 使用独立颜色、图标和“只读、可追溯”标签，不伪装成人员或普通系统消息。
- 查询结果旁边固定展示数据集、时间范围、权限范围和引用来源。
- 外部模型失败时显示原因和重试路径，不只显示“系统错误”。

### 4. Carbon：高密度业务表格需要明确工具栏和行级操作

Carbon Data Table 将筛选、批量操作、排序和行内容放在稳定的 toolbar 与表格结构中，适合采购订单、库存批次和异常清单。[Carbon Data Table](https://carbondesignsystem.com/components/data-table/usage/)

对 ChemicalOps 的启发：

- 表格上方统一放搜索、状态、日期和更多筛选。
- 详情使用右侧抽屉，不跳离列表上下文。
- 风险状态使用语义色，但不让颜色成为唯一信息来源。

### 5. Coupa：采购平台强调全局入口、状态和采购闭环

Coupa Supplier Portal 的官方文档展示了全局工具栏、通知、帮助入口，以及采购订单、发票和付款等业务模块的统一入口。[Coupa Supplier Portal](https://docs.coupa.com/en/supplier-documentation/coupa-for-suppliers/the-coupa-supplier-portal-or-csp/how-to-use-the-coupa-supplier-portal-for-the-first-time)

对 ChemicalOps 的启发：

- 顶部保留全局搜索、通知和帮助入口。
- 采购申请、采购订单、供应商和财务处理使用一致的页面结构。
- 每一个业务对象都要能看见当前状态、负责人、下一步动作和相关单据。

## 二、ChemicalOps 视觉方向

关键词：安全、清晰、专业、可追溯、轻量化企业软件。

### 颜色

- Ink Navy：`#0D2133`，侧栏、主标题和高对比区域。
- Chemical Teal：`#0D9B91`，主按钮、选中状态和 AI 入口。
- Mint Surface：`#E8F7F3`，AI 卡片、成功状态和轻提示。
- Warm White：`#F8FAF9`，应用背景。
- Risk Amber：`#D98C22`，临期、待处理和警告。
- Risk Coral：`#D9534F`，逾期、不合格和高风险。
- Text Gray：`#62737A`，辅助说明和次级数据。

### 排版和布局

- 中文正文优先使用系统无衬线字体，标题使用较高字重和短句。
- 基础间距 4px，常用间距 8 / 12 / 16 / 24 / 32px。
- 桌面端采用“深色侧栏 + 浅色工作区 + 右侧详情抽屉”。
- 主页面最多保留 3 个视觉层级：页面标题、业务指标、操作内容。
- 卡片减少装饰性阴影，优先使用边框、留白和状态色建立层次。
- 控制小号文字数量：卡片和提示框只保留必要的标题、数值和一行说明，不堆叠类似红框中的多行小字。
- 红色区域优先表达“发生了什么”和“需要做什么”，详细解释放到详情抽屉、展开面板或帮助入口。
- 辅助文字必须有明确层级和足够对比度，不能用密集的浅灰小字填充视觉空白。

## 三、参考图清单

1. [登录页参考图](ui-reference/01-login.png)：品牌叙事与登录表单分离，强调安全与可信。
2. [运营总览参考图](ui-reference/02-overview.png)：KPI、趋势、风险队列和供应商绩效组成工作台。
3. [AI 工作台参考图](ui-reference/03-ai-workspace.png)：对话、结构化结果和查询依据三栏联动。
4. [采购管理参考图](ui-reference/04-procurement.png)：列表、筛选、状态、详情抽屉和流程时间线。
5. [库存与质量参考图](ui-reference/05-inventory-quality.png)：库存表、质量分布、临期/冻结/待检风险队列。

## 四、后续实现顺序

1. 先重做登录页和全局布局，建立颜色、间距、按钮、输入框和表格 tokens。
2. 重做运营总览，把业务状态和风险事项放到首屏。
3. 重做采购、库存、质量等列表页，统一筛选、表格和详情抽屉。
4. 重做 AI 助手，将查询结果、引用和执行状态整合到工作台。
5. 完成响应式、键盘操作、焦点状态、错误态和空状态检查。

## 五、设计审查清单

- [ ] 登录页在浅色和深色环境下均保持可读性。
- [ ] 所有按钮、输入框、表格行具备 hover、focus、disabled、error 状态。
- [ ] 风险信息同时使用文字、图标和颜色表达。
- [ ] AI 结果明确标注 AI 身份、只读边界和数据来源。
- [ ] 桌面、平板和窄窗口下不出现横向溢出。
- [ ] 采购、库存和质量页面可从概览卡片下钻到详情。
