"""高风险路由的服务端权限拆分回归，不使用或记录登录口令。"""

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
import pytest

from app.core.auth import get_current_user
from app.main import app
from app.core.security import hash_password
from app.modules.system.model import Permission, Role, RolePermission, User, UserRole
from app.modules.rfqs.model import RFQ
from app.modules.inventory.model import (
    InventoryBalance,
    InventoryBalanceStatusLog,
    InventoryTransaction,
    Warehouse,
    WarehouseLocation,
)
from app.modules.insights.model import InsightSnapshot
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.system.model import Department
from app.modules.suppliers.model import Supplier
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


def test_system_admin_role_cannot_be_disabled_through_single_or_batch_routes(
    client: TestClient, db_session
) -> None:
    role = db_session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
    assert role is not None and role.status == "ACTIVE"

    with as_demo_role(db_session, "SYS_ADMIN"):
        single = client.patch(
            f"/api/v1/system/roles/{role.id}", json={"status": "INACTIVE"}
        )
        batch = client.post(
            "/api/v1/batch/system.roles/delete", json={"ids": [role.id]}
        )

    db_session.refresh(role)
    assert single.status_code == 400
    assert batch.status_code == 400
    assert role.status == "ACTIVE"


def test_system_admin_cannot_disable_own_account_through_single_or_batch_routes(
    client: TestClient, db_session
) -> None:
    admin_role = db_session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
    admin = db_session.scalar(
        select(User).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == admin_role.id, User.status == "ACTIVE")
        .order_by(User.id)
    )
    assert admin_role is not None and admin is not None

    with as_demo_role(db_session, "SYS_ADMIN"):
        update = client.patch(
            f"/api/v1/system/users/{admin.id}", json={"status": "INACTIVE"}
        )
        delete = client.delete(f"/api/v1/system/users/{admin.id}")
        batch = client.post(
            "/api/v1/batch/system.users/delete", json={"ids": [admin.id]}
        )

    db_session.refresh(admin)
    assert update.status_code == 400
    assert delete.status_code == 400
    assert batch.status_code == 400
    assert admin.status == "ACTIVE"


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


def test_read_only_warehouse_cannot_create_recall_report(client: TestClient, db_session) -> None:
    """Persisting a recall report is a write action even when its source is readable."""
    role = db_session.scalar(select(Role).where(Role.role_code == "WAREHOUSE"))
    read_permission = db_session.scalar(
        select(Permission).where(Permission.permission_code == "warehouse.inventory.read")
    )
    write_permission = db_session.scalar(
        select(Permission).where(Permission.permission_code == "warehouse.inventory.write")
    )
    balance = db_session.scalar(
        select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id)
    )
    assert role is not None and read_permission is not None and write_permission is not None
    assert balance is not None
    assert db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == read_permission.id,
        )
    ) is not None
    write_link = db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == write_permission.id,
        )
    )
    assert write_link is not None
    db_session.delete(write_link)
    db_session.flush()
    reports_before = db_session.scalar(
        select(func.count(InsightSnapshot.id)).where(
            InsightSnapshot.kind == "batch-recall-report",
            InsightSnapshot.object_id == balance.id,
        )
    )

    with as_demo_role(db_session, "WAREHOUSE"):
        response = client.post(
            f"/api/v1/insights/batch-impact/{balance.id}/recall-reports"
        )
    assert response.status_code == 403
    reports_after = db_session.scalar(
        select(func.count(InsightSnapshot.id)).where(
            InsightSnapshot.kind == "batch-recall-report",
            InsightSnapshot.object_id == balance.id,
        )
    )
    assert reports_after == reports_before


def test_combined_technical_and_warehouse_roles_keep_warehouse_scope(
    client: TestClient, db_session
) -> None:
    """Merged page permissions must not expand warehouse ownership scope."""
    technical_role = db_session.scalar(select(Role).where(Role.role_code == "TECHNICAL"))
    warehouse_role = db_session.scalar(select(Role).where(Role.role_code == "WAREHOUSE"))
    user = db_session.scalar(
        select(User).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == technical_role.id, User.status == "ACTIVE")
        .order_by(User.id)
    )
    other_user = db_session.scalar(
        select(User).where(User.status == "ACTIVE", User.id != user.id).order_by(User.id)
    )
    assert technical_role is not None and warehouse_role is not None
    assert user is not None and other_user is not None

    own_warehouse = Warehouse(
        warehouse_code=f"RBAC-OWN-{user.id}", warehouse_name="RBAC 本人授权仓库",
        manager_id=user.id, status="ACTIVE",
    )
    foreign_warehouse = Warehouse(
        warehouse_code=f"RBAC-OTHER-{user.id}", warehouse_name="RBAC 他人仓库",
        manager_id=other_user.id, status="ACTIVE",
    )
    db_session.add_all((own_warehouse, foreign_warehouse))
    db_session.flush()
    source_balance = db_session.scalar(
        select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id)
    )
    assert source_balance is not None
    foreign_location = WarehouseLocation(
        warehouse_id=foreign_warehouse.id,
        location_code=f"RBAC-OTHER-LOC-{user.id}",
        location_name="RBAC 他人仓库库位",
        status="ACTIVE",
    )
    db_session.add(foreign_location)
    db_session.flush()
    foreign_balance = InventoryBalance(
        warehouse_id=foreign_warehouse.id,
        location_id=foreign_location.id,
        product_id=source_balance.product_id,
        batch_id=source_balance.batch_id,
        unit_id=source_balance.unit_id,
        quantity=1,
        locked_quantity=0,
        status="AVAILABLE",
    )
    db_session.add(foreign_balance)
    db_session.flush()
    db_session.add_all((
        InventoryTransaction(
            transaction_no=f"RBAC-TX-{user.id}",
            transaction_type="ADJUSTMENT",
            warehouse_id=foreign_warehouse.id,
            location_id=foreign_location.id,
            product_id=source_balance.product_id,
            batch_id=source_balance.batch_id,
            unit_id=source_balance.unit_id,
            quantity=1,
            operator_id=user.id,
            note="RBAC scope fixture",
        ),
        InventoryBalanceStatusLog(
            balance_id=foreign_balance.id,
            previous_status="AVAILABLE",
            new_status="FROZEN",
            reason="RBAC scope fixture",
            operator_id=user.id,
        ),
    ))
    db_session.add(UserRole(user_id=user.id, role_id=warehouse_role.id))
    db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        warehouses = client.get("/api/v1/inventory/warehouses")
        assert warehouses.status_code == 200
        visible_ids = {row["id"] for row in warehouses.json()}
        assert own_warehouse.id in visible_ids
        assert foreign_warehouse.id not in visible_ids

        balances = client.get("/api/v1/inventory/balances", params={"page_size": 100})
        assert balances.status_code == 200
        assert all(row["warehouse_id"] != foreign_warehouse.id for row in balances.json()["items"])
        expected_balance_total = db_session.scalar(
            select(func.count(InventoryBalance.id))
            .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
            .where((Warehouse.manager_id == user.id) | Warehouse.manager_id.is_(None))
        )
        assert balances.json()["total"] == expected_balance_total
        assert client.get(
            "/api/v1/inventory/balances",
            params={"warehouse_id": foreign_warehouse.id},
        ).status_code == 404
        assert client.get(f"/api/v1/inventory/warehouses/{foreign_warehouse.id}/locations").status_code == 404
        assert client.get(
            f"/api/v1/inventory/balances/{foreign_balance.id}/status-logs"
        ).status_code == 404

        transactions = client.get("/api/v1/inventory/transactions", params={"page_size": 100})
        assert transactions.status_code == 200
        assert all(row["warehouse_id"] != foreign_warehouse.id for row in transactions.json()["items"])
        expected_transaction_total = db_session.scalar(
            select(func.count(InventoryTransaction.id))
            .join(Warehouse, Warehouse.id == InventoryTransaction.warehouse_id)
            .where((Warehouse.manager_id == user.id) | Warehouse.manager_id.is_(None))
        )
        assert transactions.json()["total"] == expected_transaction_total
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_buyer_request_list_count_and_detail_share_department_scope(
    client: TestClient, db_session
) -> None:
    buyer = db_session.scalar(select(User).where(User.username == "buyer", User.status == "ACTIVE"))
    assert buyer is not None
    suffix = uuid4().hex[:10]
    own_department = Department(
        department_code=f"RBAC-{suffix}", department_name="RBAC 授权部门", status="ACTIVE",
    )
    other_department = Department(
        department_code=f"RBAC-OTHER-{suffix}", department_name="RBAC 其他部门", status="ACTIVE",
    )
    db_session.add_all((own_department, other_department))
    db_session.flush()
    buyer.department_id = own_department.id
    same_department_user = User(
        username=f"rbac-peer-{suffix}", password_hash="unused-test-hash",
        display_name="RBAC 同部门申请人", department_id=own_department.id, status="ACTIVE",
    )
    other_department_user = User(
        username=f"rbac-cross-{suffix}", password_hash="unused-test-hash",
        display_name="RBAC 跨部门申请人", department_id=other_department.id, status="ACTIVE",
    )
    db_session.add_all((same_department_user, other_department_user))
    db_session.flush()

    own_request = PurchaseRequest(
        request_no=f"RBAC-{suffix}", applicant_id=buyer.id, department_id=own_department.id,
        purpose="本人范围用例", status="DRAFT",
    )
    same_department_request = PurchaseRequest(
        request_no=f"RBAC-SAME-{suffix}", applicant_id=same_department_user.id,
        department_id=own_department.id, purpose="同部门范围用例", status="DRAFT",
    )
    cross_department_request = PurchaseRequest(
        request_no=f"RBAC-CROSS-{suffix}", applicant_id=other_department_user.id,
        department_id=other_department.id, purpose="跨部门范围用例", status="DRAFT",
    )
    db_session.add_all((own_request, same_department_request, cross_department_request))
    db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: buyer
    try:
        listed = client.get("/api/v1/purchase-requests", params={"page_size": 100})
        assert listed.status_code == 200
        assert listed.json()["total"] == 2
        assert {row["id"] for row in listed.json()["items"]} == {
            own_request.id, same_department_request.id,
        }
        assert client.get(f"/api/v1/purchase-requests/{same_department_request.id}").status_code == 200
        assert client.get(f"/api/v1/purchase-requests/{cross_department_request.id}").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_supplier_portal_cannot_call_internal_ai_api(client: TestClient, db_session) -> None:
    with as_demo_role(db_session, "SUPPLIER_PORTAL"):
        response = client.get("/api/v1/ai/agent/tools")
        assert response.status_code == 403


def test_business_insights_require_ai_permission_in_addition_to_resource_permission(
    client: TestClient, db_session
) -> None:
    role = db_session.scalar(select(Role).where(Role.role_code == "WAREHOUSE"))
    permission = db_session.scalar(
        select(Permission).where(Permission.permission_code == "ai.workspace.read")
    )
    assert role is not None and permission is not None
    binding = db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    assert binding is not None
    db_session.delete(binding)
    db_session.flush()

    with as_demo_role(db_session, "WAREHOUSE"):
        response = client.get("/api/v1/insights/batch-impact/999999")

    assert response.status_code == 403


def test_procurement_role_cannot_read_financial_records_through_insight(
    client: TestClient, db_session
) -> None:
    """Order visibility alone must not expose linked reconciliation documents."""
    with as_demo_role(db_session, "BUYER"):
        response = client.get("/api/v1/insights/finance-difference/999999")

    assert response.status_code == 403


def test_procurement_role_cannot_read_or_write_finance_checklists(
    client: TestClient, db_session
) -> None:
    with as_demo_role(db_session, "BUYER"):
        responses = [
            client.get("/api/v1/insights/finance-difference/1/checks"),
            client.get("/api/v1/insights/finance-difference/1/assignees"),
            client.post("/api/v1/insights/finance-difference/1/checks", params={"snapshot_id": 1}),
            client.patch(
                "/api/v1/insights/finance-difference/1/checks/1",
                json={"finding": "权限边界回归"},
            ),
            client.get("/api/v1/insights/finance-difference/1/checks/1/events"),
        ]

    assert [response.status_code for response in responses] == [403] * len(responses)


def test_supplier_insight_omits_quality_evidence_without_quality_permission(
    client: TestClient, db_session
) -> None:
    from app.modules.system import crud as system_crud

    buyer = db_session.scalar(select(User).where(User.username == "buyer", User.status == "ACTIVE"))
    supplier = db_session.scalar(select(Supplier).order_by(Supplier.id))
    assert buyer is not None and supplier is not None
    grants = system_crud.get_user_permission_codes(db_session, buyer.id)
    assert "master.suppliers.read" in grants
    assert "ai.workspace.read" in grants
    assert "quality.acceptances.read" not in grants
    app.dependency_overrides[get_current_user] = lambda: buyer
    try:
        response = client.get(f"/api/v1/insights/supplier-score/{supplier.id}")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    assert all(item["label"] != "验收结果样本" for item in response.json()["evidence"])


def test_msds_insight_requires_chemical_read_even_when_inventory_is_readable(
    client: TestClient, db_session
) -> None:
    role = db_session.scalar(select(Role).where(Role.role_code == "WAREHOUSE"))
    permission = db_session.scalar(
        select(Permission).where(Permission.permission_code == "master.chemicals.read")
    )
    assert role is not None and permission is not None
    binding = db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    assert binding is not None
    db_session.delete(binding)
    db_session.flush()

    with as_demo_role(db_session, "WAREHOUSE"):
        response = client.get("/api/v1/insights/msds-change/1")

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
