"""内置角色授权基线的纯静态回归。"""

from scripts.seed_demo_accounts import PERMISSIONS, ROLE_SCOPES


def test_dashboard_and_ai_baseline_for_all_roles() -> None:
    assert len(ROLE_SCOPES) == 12
    assert all("dashboard.read" in scope for scope in ROLE_SCOPES.values())
    assert all("ai.workspace.read" in ROLE_SCOPES[role] for role in ROLE_SCOPES if role != "SUPPLIER_PORTAL")
    assert "ai.workspace.read" not in ROLE_SCOPES["SUPPLIER_PORTAL"]


def test_rfq_comparison_and_award_are_split_by_role() -> None:
    assert "procurement.rfqs.compare" in ROLE_SCOPES["BUYER"]
    assert "procurement.rfqs.award" not in ROLE_SCOPES["BUYER"]
    assert {"procurement.rfqs.compare", "procurement.rfqs.award"} <= ROLE_SCOPES["PROCUREMENT_MANAGER"]
    assert {"procurement.rfqs.compare", "procurement.rfqs.award"} <= ROLE_SCOPES["SYS_ADMIN"]


def test_technical_and_finance_roles_have_no_general_expiry_or_cost_access() -> None:
    for role in ("TECHNICAL", "FINANCE_VIEWER", "FINANCE_CLERK", "FINANCE_MANAGER"):
        assert "warehouse.inventory.expiry.read" not in ROLE_SCOPES[role]
        assert "warehouse.inventory.cost.read" not in ROLE_SCOPES[role]
    assert not {"warehouse.inventory.read", "warehouse.inventory.expiry.read"} & ROLE_SCOPES["TECHNICAL"]
    assert "warehouse.inventory.cost.read" not in ROLE_SCOPES["WAREHOUSE"]
    assert "warehouse.inventory.cost.write" in ROLE_SCOPES["WAREHOUSE"]


def test_admin_only_destructive_and_export_permissions() -> None:
    admin = ROLE_SCOPES["SYS_ADMIN"]
    destructive = {
        "master.chemicals.delete", "master.products.delete", "master.suppliers.deactivate",
    }
    exports = {code for code, *_ in PERMISSIONS if code.endswith(".export")}
    assert destructive | exports <= admin
    for role, scope in ROLE_SCOPES.items():
        if role != "SYS_ADMIN":
            assert not destructive & scope
            assert not exports & scope


def test_cross_domain_writes_and_supplier_ai_are_not_granted() -> None:
    manager = ROLE_SCOPES["PROCUREMENT_MANAGER"]
    assert not {
        "master.chemicals.write", "master.products.write", "warehouse.deliveries.write",
        "quality.acceptances.write", "warehouse.inventory.write",
        "warehouse.inventory.issue.execute", "warehouse.inventory.cost.write",
    } & manager
    assert "warehouse.inventory.issue.read" not in ROLE_SCOPES["BUYER"]
    assert "warehouse.inventory.read" not in ROLE_SCOPES["BUYER"]
    assert "warehouse.inventory.read" not in ROLE_SCOPES["TECHNICAL"]
    assert "ai.workspace.read" not in ROLE_SCOPES["SUPPLIER_PORTAL"]


def test_buyer_can_handle_replenishments_without_approval() -> None:
    assert {"procurement.replenishment.read", "procurement.replenishment.write"} <= ROLE_SCOPES["BUYER"]
    assert "procurement.replenishment.approve" not in ROLE_SCOPES["BUYER"]


def test_quality_assignment_is_reserved_for_managers() -> None:
    assert "quality.acceptances.assign" in ROLE_SCOPES["QUALITY_MANAGER"]
    assert "quality.acceptances.assign" in ROLE_SCOPES["SYS_ADMIN"]
    assert "quality.acceptances.assign" not in ROLE_SCOPES["QUALITY"]
    assert "quality.acceptances.write" in ROLE_SCOPES["QUALITY"]
