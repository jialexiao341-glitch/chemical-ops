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
    return [(key, spec) for key, spec in CATALOG.items() if dataset_is_available(db, user, key)]


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
                "version": "1.0",
                "risk": "READ_ONLY",
                "input_schema": spec.input_schema.model_json_schema(),
            }
            for spec in TOOLS.values()
            if admin or spec.permission in permissions
        ]

    datasets = []
    if "ai.workspace.read" in permissions or admin:
        datasets = [_dataset_description(key, spec) for key, spec in available_datasets(db, user)]

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

    document_search = "ai.workspace.read" in permissions or admin
    material = {
        "contract_version": CONTRACT_VERSION,
        "agent_tools": tools,
        "analytics_datasets": datasets,
        "document_search": document_search,
        "resource_scopes": resource_scopes,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:20]
    return CapabilityManifest(**material, digest=digest)
