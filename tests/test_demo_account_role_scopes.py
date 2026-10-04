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
