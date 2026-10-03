from scripts.seed_demo_accounts import REVOKED_ROLE_PERMISSIONS, ROLE_SCOPES


def test_dashboard_is_available_to_every_internal_demo_role() -> None:
    internal_roles = set(ROLE_SCOPES) - {"SUPPLIER_PORTAL"}

    assert internal_roles
    assert all("dashboard.read" in ROLE_SCOPES[role] for role in internal_roles)
    assert "dashboard.read" not in ROLE_SCOPES["SUPPLIER_PORTAL"]


def test_buyer_can_read_but_cannot_write_product_master_data() -> None:
    buyer_scope = ROLE_SCOPES["BUYER"]

    assert "master.products.read" in buyer_scope
    assert "master.products.write" not in buyer_scope
    assert "master.products.write" in REVOKED_ROLE_PERMISSIONS["BUYER"]
