from scripts.seed_demo_accounts import REVOKED_ROLE_PERMISSIONS, ROLE_SCOPES


def test_dashboard_is_available_to_every_demo_role() -> None:
    all_roles = set(ROLE_SCOPES)

    assert all_roles
    assert all("dashboard.read" in ROLE_SCOPES[role] for role in all_roles)
    assert "ai.workspace.read" not in ROLE_SCOPES["SUPPLIER_PORTAL"]


def test_buyer_can_read_but_cannot_write_product_master_data() -> None:
    buyer_scope = ROLE_SCOPES["BUYER"]

    assert "master.products.read" in buyer_scope
    assert "master.products.write" not in buyer_scope
    assert "master.products.write" in REVOKED_ROLE_PERMISSIONS["BUYER"]


def test_supplier_master_maintenance_and_order_approval_belong_to_manager() -> None:
    buyer_scope = ROLE_SCOPES["BUYER"]
    manager_scope = ROLE_SCOPES["PROCUREMENT_MANAGER"]

    assert "master.suppliers.read" in buyer_scope
    assert "master.suppliers.write" not in buyer_scope
    assert "master.suppliers.write" in REVOKED_ROLE_PERMISSIONS["BUYER"]
    assert "master.suppliers.write" in manager_scope
    assert "procurement.orders.approve" not in buyer_scope
    assert "procurement.orders.approve" in manager_scope
    assert "procurement.rfqs.compare" not in buyer_scope
    assert "procurement.rfqs.compare" in REVOKED_ROLE_PERMISSIONS["BUYER"]
    assert "procurement.rfqs.compare" in manager_scope
    assert {"procurement.rfqs.write", "procurement.rfqs.quote", "procurement.orders.write"} <= buyer_scope


def test_technical_role_can_manage_personal_issue_requests_but_not_warehouse_operations() -> None:
    technical_scope = ROLE_SCOPES["TECHNICAL"]
    personal_issue_permissions = {
        "warehouse.inventory.issue.read", "warehouse.inventory.issue.write",
    }
    warehouse_permissions = {
        "warehouse.inventory.transfer.read", "warehouse.inventory.transfer.write",
        "warehouse.inventory.stocktake.read", "warehouse.inventory.stocktake.write",
    }

    assert {"master.chemicals.read", "master.chemicals.write",
            "master.products.read", "master.products.write"} <= technical_scope
    assert personal_issue_permissions <= technical_scope
    assert not (warehouse_permissions & technical_scope)
    assert warehouse_permissions <= REVOKED_ROLE_PERMISSIONS["TECHNICAL"]
    assert "warehouse.inventory.issue.approve" not in technical_scope
    assert "warehouse.inventory.issue.execute" not in technical_scope
