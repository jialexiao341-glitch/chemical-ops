"""为路由理解器构建最小化、按当前权限过滤的能力清单。"""

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai.agent_tools import TOOLS
from app.modules.ai.catalog import CATALOG, DatasetSpec
from app.modules.ai.schema import CapabilityManifest
from app.modules.inventory.service import accessible_warehouse_ids
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


CONTRACT_VERSION = "1"

AGENT_TASK_REQUIREMENTS = {
    "inventory": frozenset({"catalog.search_products", "inventory.query_available"}),
    "quotes": frozenset({"catalog.search_products", "supplier_quotes.find_rfq_items", "supplier_quotes.compare"}),
    "purchase_request": frozenset({"purchase_requests.get_by_no"}),
    "order_trace": frozenset({"purchase_orders.trace_by_no"}),
    "quality_acceptance": frozenset({"quality_acceptances.get_by_no"}),
    "delivery": frozenset({"deliveries.get_by_no"}),
    "finance_reconciliation": frozenset({"finance_reconciliations.get_by_no"}),
    "supplier": frozenset({"suppliers.get_by_code"}),
}

# 入口说明是产品契约；是否可用仍由已注册 handler、开关和实时权限决定。
ACTION_ENTRIES = {
    "purchase_request.create_draft": ("创建采购申请草稿", "chat", "purchase_draft"),
    "purchase_request.update_draft": ("修改采购申请草稿", "chat", "purchase_update"),
    "purchase_request.submit": ("提交采购申请", "chat", "purchase_submit"),
    "rfq.create_draft": ("基于已审批申请创建询价草稿", "chat", "rfq_draft"),
    "rfq.send": ("发送询价", "business_page", None),
    "rfq.select_quote": ("确认中选报价", "business_page", None),
    "purchase_order.create_draft": ("检查条款并准备采购订单草稿", "business_page", None),
}

# Composite datasets require every listed read permission. The base DatasetSpec.permission
# remains required as well, matching the execution-time checks in Text2SQL.
_COMPOSITE_DATASET_PERMISSIONS: dict[str, frozenset[str]] = {
    "overdue_unfulfilled_orders": frozenset({"procurement.orders.read", "warehouse.inventory.read", "master.products.read"}),
    "weekly_order_risks": frozenset({"procurement.orders.read", "warehouse.deliveries.read"}),
    "accepted_orders_finance_gaps": frozenset({
        "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read",
        "finance.reconciliations.read", "finance.invoices.read", "finance.payments.read",
        "finance.settlements.read",
    }),
    "supplier_quote_delivery_profile": frozenset({
        "master.suppliers.read", "procurement.rfqs.read", "procurement.orders.read",
        "warehouse.deliveries.read", "operations.exceptions.read",
    }),
}


def agent_enabled() -> bool:
    return get_settings().agent_enabled


def required_dataset_permissions(key: str, spec: DatasetSpec) -> frozenset[str]:
    return frozenset({spec.permission, *_COMPOSITE_DATASET_PERMISSIONS.get(key, frozenset())})


def dataset_accessible_by_codes(key: str, spec: DatasetSpec, role_codes: set[str], permission_codes: set[str]) -> bool:
    return "SYS_ADMIN" in role_codes or required_dataset_permissions(key, spec) <= permission_codes


def dataset_is_available(db: Session, user: User, key: str) -> bool:
    """复用的当前时点 dataset 授权判定；执行器仍在每次查询时调用。"""
    spec = CATALOG.get(key)
    if spec is None:
        return False
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    return dataset_accessible_by_codes(key, spec, roles, permissions)


def available_datasets(db: Session, user: User) -> list[tuple[str, DatasetSpec]]:
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    return [(key, spec) for key, spec in CATALOG.items()
            if dataset_accessible_by_codes(key, spec, roles, permissions)]


def _dataset_description(key: str, spec: DatasetSpec) -> dict[str, Any]:
    return {
        "key": key,
        "label": spec.label,
        "metrics": sorted(spec.metrics),
        "dimensions": sorted(spec.dimensions),
        "filters": sorted(spec.filters),
        "times": sorted(spec.times),
        "outputs": sorted(spec.outputs),
        "derived_outputs": sorted(spec.derived_outputs),
    }


def analytics_catalog(db: Session, user: User) -> list[dict[str, Any]]:
    """规划阶段使用与路由相同的当前可用数据集契约。"""
    return [_dataset_description(key, spec) for key, spec in available_datasets(db, user)]


def describe_capabilities(manifest: CapabilityManifest) -> str:
    """功能介绍从本轮清单生成，避免静态文案承诺尚不可执行的能力。"""
    sections = ["我是化运助手，可以根据当前可用能力帮助你查询和分析业务数据。"]
    if manifest.analytics_datasets:
        sections.append("业务统计与关联分析：" + "、".join(item["label"] for item in manifest.analytics_datasets) + "。")
    if manifest.agent_tools:
        ready_tools = set().union(*(AGENT_TASK_REQUIREMENTS[task] for task in manifest.agent_tasks))
        descriptions = [item["description"] for item in manifest.agent_tools
                        if item["name"] in ready_tools and item["name"] not in {"catalog.search_products", "supplier_quotes.find_rfq_items"}]
        if descriptions:
            sections.append("记录查询：\n" + "\n".join("- " + label for label in descriptions))
    if manifest.document_search:
        sections.append("可以检索化学品资料并依据检索结果回答；没有资料依据时会说明缺失。")
    chat_actions = [item["label"] for item in manifest.action_proposals if item["entrypoint"] == "chat"]
    page_actions = [item["label"] for item in manifest.action_proposals if item["entrypoint"] == "business_page"]
    if chat_actions:
        sections.append("可以在聊天中准备以下提案，核对预览并明确确认后执行：" + "、".join(chat_actions) + "。")
    if page_actions:
        sections.append("以下提案从对应业务页面发起并确认：" + "、".join(page_actions) + "。")
    if not manifest.agent_tools and not manifest.analytics_datasets and not manifest.document_search and not manifest.action_proposals:
        sections.append("当前没有可用的业务查询、资料检索或动作提案能力，请检查功能开关和账号配置。")
    sections.append("审批、正式下单、收货、库存变动和付款需在相应业务流程中办理；查询和提案准备本身不会执行这些操作。")
    return "\n\n".join(sections)


def build_capability_manifest(db: Session, user: User) -> CapabilityManifest:
    """按当前 RBAC、Agent 总开关及仓库资源范围生成本轮路由上下文。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    admin = "SYS_ADMIN" in roles
    enabled = agent_enabled()

    tools = []
    if enabled:
        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                **spec.governance_metadata(),
                "input_schema": spec.input_schema.model_json_schema(),
            }
            for spec in TOOLS.values()
            if admin or {spec.permission, *spec.additional_permissions} <= permissions
        ]

    datasets = []
    if enabled and ("ai.workspace.read" in permissions or admin):
        datasets = [_dataset_description(key, spec) for key, spec in CATALOG.items()
                    if dataset_accessible_by_codes(key, spec, roles, permissions)]

    from app.modules.ai import action_handlers
    actions = []
    if enabled and (admin or "ai.workspace.read" in permissions):
        for action_type in action_handlers.registered_action_types():
            if action_type not in ACTION_ENTRIES:
                continue
            if not admin and not action_handlers.required_permissions(action_type) <= permissions:
                continue
            label, entrypoint, purpose = ACTION_ENTRIES[action_type]
            actions.append({"action_type": action_type, "label": label, "entrypoint": entrypoint,
                            "purpose": purpose, "requires_confirmation": True})

    resource_scopes: list[str] = []
    if enabled and any(item["name"] == "inventory.query_available" for item in tools):
        warehouse_ids = accessible_warehouse_ids(db, user)
        if warehouse_ids is None:
            resource_scopes.append("all_active_warehouses")
        elif warehouse_ids:
            resource_scopes.append("currently_accessible_warehouses")
        else:
            # Tool remains permission-gated; this tells routing no warehouse result is currently visible.
            resource_scopes.append("no_accessible_warehouses")

    document_search = enabled and ("ai.workspace.read" in permissions or admin)
    material = {
        "contract_version": CONTRACT_VERSION,
        "agent_tools": tools,
        "analytics_datasets": datasets,
        "document_search": document_search,
        "resource_scopes": resource_scopes,
        "action_proposals": actions,
        "agent_tasks": [task for task, required in AGENT_TASK_REQUIREMENTS.items()
                        if required <= {item["name"] for item in tools}],
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:20]
    return CapabilityManifest(**material, digest=digest)
