"""ChemicalOps AI 助手模块。

入口层保留 HTTP 接口、服务、共享数据契约和数据库模型；其余实现按职责分类：
agent_execution 为 Agent 编排，business_queries 为只读查询，conversation_context 为上下文与历史，
action_management 为写入提案与草稿，model_access 为模型接入，quality_operations 为质量与运营，
shared_utils 为共用规则。权限、事务和模型调用边界以各模块自身的说明与实现为准。
"""
