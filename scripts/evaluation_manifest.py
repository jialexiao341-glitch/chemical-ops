"""评测用能力清单：与生产路由注入的结构一致，权限由真实账号裁剪。

路由提示词要求依据 capabilities 判断执行模式和任务边界。评测只发送合成问题、
不连接业务库，因此用固定的全量只读清单代表“能力完整”的账号；这不是权限测试，
真实调用仍由 RBAC 与资源范围强制校验。
"""

from __future__ import annotations

from app.modules.ai_agent.action_management import action_handlers
from app.modules.ai_agent.agent_execution.agent_tools import TOOLS
from app.modules.ai_agent.agent_execution.capabilities import ACTION_ENTRIES, AGENT_TASK_REQUIREMENTS, _dataset_description
from app.modules.ai_agent.business_queries.catalog import CATALOG
from app.modules.ai_agent.schema import CapabilityManifest


def build_manifest(digest: str) -> CapabilityManifest:
    """构造路由评测使用的只读能力清单；包含聊天与业务页面提案入口。"""
    tools = [{
        "name": spec.name,
        "description": spec.description,
        **spec.governance_metadata(),
        "input_schema": spec.input_schema.model_json_schema(),
    } for spec in TOOLS.values()]
    actions = [{
        "action_type": action_type,
        "label": ACTION_ENTRIES[action_type][0],
        "entrypoint": ACTION_ENTRIES[action_type][1],
        "purpose": ACTION_ENTRIES[action_type][2],
        "requires_confirmation": True,
    } for action_type in action_handlers.registered_action_types() if action_type in ACTION_ENTRIES]
    return CapabilityManifest(
        contract_version="1",
        digest=digest,
        agent_tools=tools,
        analytics_datasets=[_dataset_description(key, spec) for key, spec in CATALOG.items()],
        document_search=True,
        resource_scopes=["all_active_warehouses"],
        action_proposals=actions,
        agent_tasks=sorted(AGENT_TASK_REQUIREMENTS),
    )