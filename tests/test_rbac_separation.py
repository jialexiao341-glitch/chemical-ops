"""高风险路由的服务端权限拆分回归，不使用或记录登录口令。"""

from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
import pytest

from app.core.auth import get_current_user
from app.main import app
from app.core.security import hash_password
from app.modules.system.model import Permission, Role, RolePermission, User, UserRole
from app.modules.rfqs.model import RFQ
from tests.conftest import login
from scripts.seed_demo_accounts import ROLE_SCOPES


@contextmanager
def as_demo_role(db_session, role_code: str):
    user = db_session.scalar(
        select(User).join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.role_code == role_code, User.status == "ACTIVE")
        .order_by(User.id)
    )
    assert user is not None, f"missing active demo account for role {role_code}"
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield {}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_buyer_can_compare_but_cannot_award(client: TestClient, db_session) -> None:
    with as_demo_role(db_session, "BUYER"):
        comparison = client.post("/api/v1/rfqs/999999/comparison")
        award = client.post(
            "/api/v1/rfqs/999999/select-quote",
            json={"comparison_id": 1, "quote_id": 1, "selection_reason": "权限测试"},
        )
        assert comparison.status_code != 403
        assert award.status_code == 403


def test_technical_cannot_read_general_inventory_or_expiry(client: TestClient, db_session) -> None:
    with as_demo_role(db_session, "TECHNICAL"):
        balances = client.get("/api/v1/inventory/balances")
        expiry = client.get("/api/v1/inventory/expiry-alerts")
        assert balances.status_code == 403
        assert expiry.status_code == 403


def test_supplier_portal_cannot_call_internal_ai_api(client: TestClient, db_session) -> None:
    with as_demo_role(db_session, "SUPPLIER_PORTAL"):
        response = client.get("/api/v1/ai/agent/tools")
        assert response.status_code == 403


@pytest.mark.parametrize("role_code", sorted(ROLE_SCOPES))
def test_all_builtin_roles_share_dashboard_and_supplier_is_excluded_from_internal_ai(
    client: TestClient, db_session, role_code: str
) -> None:
    with as_demo_role(db_session, role_code):
        dashboard = client.get("/api/v1/dashboard/overview")
        ai_tools = client.get("/api/v1/ai/agent/tools")
        products = client.get("/api/v1/products")
        inventory = client.get("/api/v1/inventory/balances")

    assert dashboard.status_code == 200
    assert ai_tools.status_code == (403 if role_code == "SUPPLIER_PORTAL" else 200)
    assert products.status_code == (200 if "master.products.read" in ROLE_SCOPES[role_code] else 403)
    assert inventory.status_code == (200 if "warehouse.inventory.read" in ROLE_SCOPES[role_code] else 403)


@pytest.mark.parametrize("role_code", sorted(ROLE_SCOPES))
def test_rfq_compare_and_award_api_actions_match_all_role_grants(
    client: TestClient, db_session, role_code: str
) -> None:
    rfq_count_before = db_session.scalar(select(func.count()).select_from(RFQ))
    with as_demo_role(db_session, role_code):
        comparison = client.post("/api/v1/rfqs/999999/comparison")
        award = client.post(
            "/api/v1/rfqs/999999/select-quote",
            json={"comparison_id": 1, "quote_id": 1, "selection_reason": "RBAC matrix"},
        )

    assert (comparison.status_code != 403) == ("procurement.rfqs.compare" in ROLE_SCOPES[role_code])
    assert (award.status_code != 403) == ("procurement.rfqs.award" in ROLE_SCOPES[role_code])
    assert db_session.scalar(select(func.count()).select_from(RFQ)) == rfq_count_before


def test_regular_writer_cannot_export_or_disable_master_data(client: TestClient, db_session) -> None:
    with as_demo_role(db_session, "TECHNICAL"):
        exported = client.post("/api/v1/batch/master.chemicals/export", json={"ids": [1]})
        disabled = client.post("/api/v1/batch/master.chemicals/delete", json={"ids": [1]})
        assert exported.status_code == 403
        assert disabled.status_code == 403


def test_warehouse_can_execute_fifo_without_receiving_cost_fields(
    client: TestClient, db_session, monkeypatch
) -> None:
    from app.modules.inventory_cost import controller
    from app.modules.inventory_cost.schema import FifoAllocationRead, FifoOutboundRead

    def fake_outbound(_db, user, _data):
        return FifoOutboundRead(
            id=1,
            request_no="TEST-FIFO",
            product_id=1,
            warehouse_id=1,
            location_id=1,
            unit_id=1,
            requested_quantity="1",
            issued_quantity="1",
            total_cost="99.00",
            currency_code="CNY",
            status="COMPLETED",
            operator_id=user.id,
            note=None,
            created_at=datetime.now(timezone.utc),
            allocations=[FifoAllocationRead(
                id=1, request_id=1, cost_layer_id=1, batch_id=1,
                quantity="1", unit_cost="99.00", total_cost="99.00",
            )],
        )

    monkeypatch.setattr(controller.service, "create_fifo_outbound", fake_outbound)
    with as_demo_role(db_session, "WAREHOUSE"):
        response = client.post(
            "/api/v1/inventory/fifo-outbounds",
            json={
                "request_no": "TEST-FIFO", "product_id": 1, "warehouse_id": 1,
                "location_id": 1, "unit_id": 1, "quantity": "1",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["total_cost"] is None
    assert body["allocations"][0]["unit_cost"] is None
    assert body["allocations"][0]["total_cost"] is None


def test_role_revocation_and_account_disable_apply_to_existing_token(
    client: TestClient, db_session, demo_password: str
) -> None:
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    assert user is not None
    user.password_hash = hash_password(demo_password)
    db_session.flush()
    token_headers = login(client, "buyer", demo_password)
    assert client.get("/api/v1/products", headers=token_headers).status_code == 200

    binding = db_session.scalar(
        select(RolePermission)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id, Permission.permission_code == "master.products.read")
    )
    assert binding is not None
    db_session.delete(binding)
    db_session.flush()
    assert client.get("/api/v1/products", headers=token_headers).status_code == 403

    supplier_role = db_session.scalar(select(Role).where(Role.role_code == "SUPPLIER_PORTAL"))
    assert supplier_role is not None
    db_session.query(UserRole).filter(UserRole.user_id == user.id).delete(synchronize_session=False)
    db_session.add(UserRole(user_id=user.id, role_id=supplier_role.id))
    db_session.flush()
    assert client.get("/api/v1/products", headers=token_headers).status_code == 403

    user.status = "INACTIVE"
    db_session.flush()
    assert client.get("/api/v1/products", headers=token_headers).status_code == 401
