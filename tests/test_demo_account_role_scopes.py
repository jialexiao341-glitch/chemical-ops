from scripts.seed_demo_accounts import ROLE_SCOPES


def test_dashboard_is_available_to_every_internal_demo_role() -> None:
    internal_roles = set(ROLE_SCOPES) - {"SUPPLIER_PORTAL"}

    assert internal_roles
    assert all("dashboard.read" in ROLE_SCOPES[role] for role in internal_roles)
    assert "dashboard.read" not in ROLE_SCOPES["SUPPLIER_PORTAL"]
