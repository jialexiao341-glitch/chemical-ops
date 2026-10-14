"""高风险路由的服务端权限拆分回归，不使用或记录登录口令。"""

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pytest

from app.core.auth import get_current_user
from app.core.db import get_db
from app.main import app
from app.core.security import hash_password
from app.modules.system.model import Permission, Role, RolePermission, User, UserRole
from app.modules.rfqs.model import RFQ
from app.modules.inventory.model import (
    InventoryBalance,
    InventoryBalanceStatusLog,
    InventoryBatch,
    InventoryIssueItem,
    InventoryIssueRequest,
    InventoryStocktakeItem,
    InventoryStocktakeRequest,
    InventoryTransferItem,
    InventoryTransferRequest,
    InventoryTransaction,
    Warehouse,
    WarehouseLocation,
)
from app.modules.insights.model import InsightSnapshot
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.operation_exceptions.model import OperationException, OperationTask
from app.modules.system.model import Department
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.schema import RoleUpdate, UserUpdate
from app.modules.system import service as system_service
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


def test_system_admin_role_cannot_lose_permissions_through_update_route(
    client: TestClient, db_session
) -> None:
    role = db_session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
    assert role is not None
    permission_ids_before = set(
        db_session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all()
    )
    assert permission_ids_before

    with as_demo_role(db_session, "SYS_ADMIN"):
        response = client.patch(
            f"/api/v1/system/roles/{role.id}",
            json={"permission_ids": [min(permission_ids_before)]},
        )

    permission_ids_after = set(
        db_session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all()
    )
    assert response.status_code == 400
    assert permission_ids_after == permission_ids_before


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

    expected_warehouse_permissions = db_session.scalars(
        select(Permission).where(Permission.permission_code.in_({
            "warehouse.inventory.issue.read",
            "warehouse.inventory.issue.execute",
            "warehouse.inventory.transfer.read",
            "warehouse.inventory.transfer.write",
            "warehouse.inventory.stocktake.read",
            "warehouse.inventory.stocktake.write",
            "warehouse.inventory.transfers.export",
        }))
    ).all()
    bound_permission_ids = set(db_session.scalars(
        select(RolePermission.permission_id).where(RolePermission.role_id == warehouse_role.id)
    ).all())
    db_session.add_all(
        RolePermission(role_id=warehouse_role.id, permission_id=permission.id)
        for permission in expected_warehouse_permissions
        if permission.id not in bound_permission_ids
    )

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
    foreign_target_location = WarehouseLocation(
        warehouse_id=foreign_warehouse.id,
        location_code=f"RBAC-OTHER-TARGET-{user.id}",
        location_name="RBAC 他人仓库目标库位",
        status="ACTIVE",
    )
    db_session.add(foreign_target_location)
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
    foreign_issue = InventoryIssueRequest(
        issue_no=f"RBAC-ISSUE-{user.id}", applicant_id=user.id,
        purpose="跨仓库领用范围", status="APPROVED",
    )
    foreign_issue.items = [InventoryIssueItem(
        line_no=1, product_id=source_balance.product_id,
        warehouse_id=foreign_warehouse.id, location_id=foreign_location.id,
        batch_id=source_balance.batch_id, unit_id=source_balance.unit_id,
        requested_quantity=1,
    )]
    foreign_transfer = InventoryTransferRequest(
        transfer_no=f"RBAC-TRANSFER-{user.id}", applicant_id=user.id,
        purpose="跨仓库调拨范围", status="APPROVED",
    )
    foreign_transfer.items = [InventoryTransferItem(
        line_no=1, product_id=source_balance.product_id,
        source_warehouse_id=foreign_warehouse.id,
        source_location_id=foreign_location.id,
        target_warehouse_id=foreign_warehouse.id,
        target_location_id=foreign_target_location.id,
        batch_id=source_balance.batch_id, unit_id=source_balance.unit_id,
        requested_quantity=1,
    )]
    foreign_stocktake = InventoryStocktakeRequest(
        stocktake_no=f"RBAC-STOCKTAKE-{user.id}", applicant_id=user.id,
        warehouse_id=foreign_warehouse.id, location_id=foreign_location.id,
        purpose="跨仓库盘点范围", status="APPROVED",
    )
    foreign_stocktake.items = [InventoryStocktakeItem(
        line_no=1, product_id=source_balance.product_id,
        location_id=foreign_location.id, batch_id=source_balance.batch_id,
        unit_id=source_balance.unit_id, book_quantity=1, counted_quantity=1,
    )]
    db_session.add_all((foreign_issue, foreign_transfer, foreign_stocktake))
    db_session.flush()
    assert "WAREHOUSE" in get_user_role_codes(db_session, user.id)
    assert "warehouse.inventory.transfer.read" in get_user_permission_codes(db_session, user.id)

    # 执行接口会在拒绝时 rollback；每个请求使用保存点，避免回滚角色和业务夹具。
    connection = db_session.connection()
    previous_db_override = app.dependency_overrides[get_db]

    def request_db():
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session

    app.dependency_overrides[get_db] = request_db
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

        issue_list = client.get("/api/v1/inventory/issue-requests", params={"page_size": 100})
        transfer_list = client.get("/api/v1/inventory/transfer-requests", params={"page_size": 100})
        stocktake_list = client.get("/api/v1/inventory/stocktakes", params={"page_size": 100})
        assert issue_list.status_code == transfer_list.status_code == stocktake_list.status_code == 200
        assert foreign_issue.id not in {row["id"] for row in issue_list.json()["items"]}
        assert foreign_transfer.id not in {row["id"] for row in transfer_list.json()["items"]}
        assert foreign_stocktake.id not in {row["id"] for row in stocktake_list.json()["items"]}
        assert client.get(f"/api/v1/inventory/issue-requests/{foreign_issue.id}").status_code == 404
        assert client.post(f"/api/v1/inventory/issue-requests/{foreign_issue.id}/execute").status_code == 404
        transfer_detail = client.get(f"/api/v1/inventory/transfer-requests/{foreign_transfer.id}")
        assert transfer_detail.status_code == 404, transfer_detail.text
        transfer_execute = client.post(f"/api/v1/inventory/transfer-requests/{foreign_transfer.id}/execute")
        assert transfer_execute.status_code == 404, transfer_execute.text
        exported = client.post(
            "/api/v1/batch/warehouse.inventory.transfers/export",
            json={"ids": [foreign_transfer.id]},
        )
        assert exported.status_code == 404, exported.text
        deleted = client.post(
            "/api/v1/batch/warehouse.inventory.transfers/delete",
            json={"ids": [foreign_transfer.id]},
        )
        assert deleted.status_code == 404, deleted.text
        assert client.get(f"/api/v1/inventory/stocktakes/{foreign_stocktake.id}").status_code == 404
        assert client.post(f"/api/v1/inventory/stocktakes/{foreign_stocktake.id}/execute").status_code == 404
        db_session.expire_all()
        assert foreign_issue.status == foreign_transfer.status == foreign_stocktake.status == "APPROVED"
        assert foreign_balance.quantity == 1
        assert "warehouse.inventory.transfer.read" in get_user_permission_codes(db_session, user.id)

        assert client.post("/api/v1/inventory/issue-requests", json={
            "purpose": "拒绝跨仓库领用申请",
            "items": [{
                "product_id": source_balance.product_id,
                "warehouse_id": foreign_warehouse.id,
                "location_id": foreign_location.id,
                "batch_id": source_balance.batch_id,
                "unit_id": source_balance.unit_id,
                "requested_quantity": "1",
            }],
        }).status_code == 404
        assert client.post("/api/v1/inventory/transfer-requests", json={
            "purpose": "拒绝跨仓库调拨",
            "items": [{
                "product_id": source_balance.product_id,
                "source_warehouse_id": foreign_warehouse.id,
                "source_location_id": foreign_location.id,
                "target_warehouse_id": foreign_warehouse.id,
                "target_location_id": foreign_target_location.id,
                "batch_id": source_balance.batch_id,
                "unit_id": source_balance.unit_id,
                "requested_quantity": "1",
            }],
        }).status_code == 404
        assert client.post("/api/v1/inventory/stocktakes", json={
            "warehouse_id": foreign_warehouse.id,
            "location_id": foreign_location.id,
            "purpose": "拒绝跨仓库盘点",
            "items": [{
                "product_id": source_balance.product_id,
                "location_id": foreign_location.id,
                "batch_id": source_balance.batch_id,
                "unit_id": source_balance.unit_id,
                "counted_quantity": "1",
            }],
        }).status_code == 404
    finally:
        app.dependency_overrides[get_db] = previous_db_override
        app.dependency_overrides.pop(get_current_user, None)


def test_notifications_keep_recipient_scope_and_read_only_permission(client: TestClient, db_session) -> None:
    """通知列表/总数/未读统计和批量已读均限制接收人，只读角色不能标记。"""
    from app.modules.notifications.model import Notification

    buyer = db_session.scalar(select(User).where(User.username == "buyer"))
    quality_manager = db_session.scalar(select(User).where(User.username == "quality_manager"))
    assert buyer is not None and quality_manager is not None
    own = Notification(recipient_id=buyer.id, notification_type="RBAC", title="本人通知", content="本人", is_read=0)
    foreign = Notification(recipient_id=quality_manager.id, notification_type="RBAC", title="他人通知", content="他人", is_read=0)
    db_session.add_all((own, foreign))
    db_session.flush()
    with as_demo_role(db_session, "BUYER"):
        listed = client.get("/api/v1/notifications", params={"page_size": 100, "unread_only": True})
        assert listed.status_code == 200
        assert own.id in {item["id"] for item in listed.json()["items"]}
        assert all(item["recipient_id"] == buyer.id for item in listed.json()["items"])
        expected = db_session.scalar(select(func.count(Notification.id)).where(
            Notification.recipient_id == buyer.id, Notification.is_read == 0))
        assert listed.json()["total"] == expected
        assert client.get("/api/v1/notifications/unread-count").json()["unread_count"] == expected
        assert client.patch(f"/api/v1/notifications/{foreign.id}/read").status_code == 404
        assert client.post("/api/v1/notifications/read-all").json()["updated_count"] == expected
    db_session.refresh(foreign)
    assert foreign.is_read == 0
    with as_demo_role(db_session, "QUALITY_MANAGER"):
        assert client.get("/api/v1/notifications").status_code == 200
        assert client.patch(f"/api/v1/notifications/{foreign.id}/read").status_code == 403
        assert client.post("/api/v1/notifications/read-all").status_code == 403
    db_session.refresh(foreign)
    assert foreign.is_read == 0


@pytest.mark.parametrize("role_code", ["PROCUREMENT_MANAGER", "SYS_ADMIN"])
@pytest.mark.parametrize("resource", ["purchase-requests", "purchase-orders", "inventory/returns", "replenishments"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_procurement_approver_cannot_review_own_work(client: TestClient, db_session, role_code, resource, action) -> None:
    """经办审批分离同时约束采购经理与管理员，通过和驳回均不得修改本人记录。"""
    from app.modules.inventory_returns.model import InventoryReturnRequest
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.replenishments.model import ReplenishmentRequest

    supplier = db_session.scalar(select(Supplier).where(Supplier.status == "ACTIVE"))
    assert supplier is not None
    with as_demo_role(db_session, role_code):
        actor = app.dependency_overrides[get_current_user]()
        suffix = uuid4().hex[:12]
        if resource == "purchase-requests":
            record = PurchaseRequest(request_no=f"RBAC-{suffix}", applicant_id=actor.id,
                                     department_id=actor.department_id, purpose="审批分离", status="APPROVING")
        elif resource == "purchase-orders":
            record = PurchaseOrder(po_no=f"RBAC-{suffix}", supplier_id=supplier.id,
                                   buyer_id=actor.id, department_id=actor.department_id, status="APPROVING")
        elif resource == "inventory/returns":
            record = InventoryReturnRequest(return_no=f"RBAC-{suffix}", supplier_id=supplier.id,
                                            applicant_id=actor.id, reason="审批分离", status="SUBMITTED")
        else:
            record = ReplenishmentRequest(replenishment_no=f"RBAC-{suffix}", supplier_id=supplier.id,
                                         applicant_id=actor.id, reason="审批分离", status="SUBMITTED")
        db_session.add(record)
        db_session.flush()
        status_before = record.status
        response = client.post(f"/api/v1/{resource}/{record.id}/{action}",
                               json={"opinion": "审批分离", "reason": "审批分离"})
        assert response.status_code == 400, response.text
        assert "本人经办" in response.json()["detail"]
        db_session.refresh(record)
        assert record.status == status_before


def test_replenishment_links_cannot_bypass_order_scope(client: TestClient, db_session) -> None:
    """补货来源订单、单独到货来源和完成订单均须属于经办人的采购范围。"""
    from app.modules.deliveries.model import Delivery
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.replenishments.model import ReplenishmentRequest

    buyer = db_session.scalar(select(User).where(User.username == "buyer"))
    template = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.status == "COMPLETED"))
    assert buyer is not None and template is not None and template.items
    other_buyer = db_session.scalar(select(User).where(User.id != buyer.id).order_by(User.id))
    assert other_buyer is not None
    buyer.department_id = None
    foreign_order = PurchaseOrder(
        po_no=f"RBAC-RP-{uuid4().hex[:12]}", supplier_id=template.supplier_id,
        buyer_id=other_buyer.id, status="ORDERED",
    )
    assert foreign_order.buyer_id != buyer.id
    db_session.add(foreign_order)
    db_session.flush()
    delivery = Delivery(
        delivery_no=f"RBAC-RP-{uuid4().hex[:12]}", po_id=foreign_order.id,
        supplier_id=foreign_order.supplier_id, status="IN_TRANSIT",
    )
    approved = ReplenishmentRequest(
        replenishment_no=f"RBAC-RP-{uuid4().hex[:12]}", supplier_id=foreign_order.supplier_id,
        applicant_id=buyer.id, reason="范围回归", status="APPROVED",
    )
    db_session.add_all((delivery, approved))
    db_session.flush()
    body = {
        "supplier_id": foreign_order.supplier_id, "reason": "拒绝越界来源",
        "items": [{"product_id": template.items[0].product_id,
                   "unit_id": template.items[0].unit_id, "requested_quantity": "1"}],
    }
    count_before = db_session.scalar(select(func.count(ReplenishmentRequest.id)))
    with as_demo_role(db_session, "BUYER"):
        for source in ({"source_po_id": foreign_order.id}, {"source_delivery_id": delivery.id}):
            response = client.post("/api/v1/replenishments", json={**body, **source})
            assert response.status_code == 404, response.text
        response = client.post(
            f"/api/v1/replenishments/{approved.id}/complete",
            json={"fulfillment_po_id": foreign_order.id},
        )
        assert response.status_code == 404, response.text
    db_session.refresh(approved)
    assert approved.status == "APPROVED" and approved.fulfillment_po_id is None
    assert db_session.scalar(select(func.count(ReplenishmentRequest.id))) == count_before


@pytest.mark.parametrize("resource", ["issue-requests", "transfer-requests", "stocktakes"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_admin_cannot_review_own_warehouse_request(client: TestClient, db_session, resource, action) -> None:
    admin = db_session.scalar(select(User).where(User.username == "system_admin"))
    warehouse = db_session.scalar(select(Warehouse))
    assert admin is not None and warehouse is not None
    models = {
        "issue-requests": (InventoryIssueRequest, "issue_no"),
        "transfer-requests": (InventoryTransferRequest, "transfer_no"),
        "stocktakes": (InventoryStocktakeRequest, "stocktake_no"),
    }
    model, number_field = models[resource]
    values = {number_field: f"RBAC-{uuid4().hex[:12]}", "applicant_id": admin.id,
              "purpose": "本人审批拒绝", "status": "SUBMITTED"}
    if resource == "stocktakes":
        values["warehouse_id"] = warehouse.id
    record = model(**values)
    db_session.add(record)
    db_session.flush()
    audit_before = record.approved_by
    with as_demo_role(db_session, "SYS_ADMIN"):
        response = client.post(f"/api/v1/inventory/{resource}/{record.id}/{action}",
                               json={"reason": "本人驳回拒绝"} if action == "reject" else None)
    assert response.status_code == 400, response.text
    assert "本人经办" in response.json()["detail"]
    db_session.refresh(record)
    assert record.status == "SUBMITTED" and record.approved_by == audit_before
    assert record.reject_reason is None


@pytest.mark.parametrize("role_code", ["SYS_ADMIN", "FINANCE_MANAGER"])
@pytest.mark.parametrize("resource,action", [
    ("invoices", "verify"), ("invoices", "reject"),
    ("payments", "approve"), ("payments", "reject"), ("settlements", "confirm"),
])
def test_finance_reviewer_cannot_review_own_record(client: TestClient, db_session, role_code, resource, action) -> None:
    from datetime import date
    from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
    from app.modules.purchase_orders.model import PurchaseOrder

    with as_demo_role(db_session, role_code):
        actor = app.dependency_overrides[get_current_user]()
        template = db_session.scalar(select(PurchaseOrder))
        assert template is not None
        order = PurchaseOrder(po_no=f"RBAC-{uuid4().hex[:12]}", supplier_id=template.supplier_id,
                              buyer_id=actor.id, status="COMPLETED")
        db_session.add(order)
        db_session.flush()
        rec = FinanceReconciliation(reconciliation_no=f"RBAC-{uuid4().hex[:12]}", po_id=order.id,
                                    supplier_id=order.supplier_id, total_amount=0,
                                    created_by=actor.id, status="CONFIRMED")
        db_session.add(rec)
        db_session.flush()
        common = dict(reconciliation_id=rec.id, po_id=order.id, supplier_id=order.supplier_id)
        if resource == "invoices":
            record = FinanceInvoice(**common, invoice_no=f"RBAC-{uuid4().hex[:12]}",
                                    invoice_number=uuid4().hex, invoice_date=date.today(), amount_excl_tax=1,
                                    amount_incl_tax=1, submitted_by=actor.id, status="SUBMITTED")
        elif resource == "payments":
            record = FinancePayment(**common, payment_no=f"RBAC-{uuid4().hex[:12]}", amount=1,
                                    payment_method="BANK_TRANSFER", requested_by=actor.id, status="REQUESTED")
        else:
            record = FinanceSettlement(**common, settlement_no=f"RBAC-{uuid4().hex[:12]}",
                                       settlement_amount=0, created_by=actor.id, status="DRAFT")
        db_session.add(record)
        db_session.flush()
        before = record.status
        response = client.post(f"/api/v1/finance/{resource}/{record.id}/{action}",
                               json={"reason": "本人驳回拒绝"} if action == "reject" else None)
        assert response.status_code == 400, response.text
        assert "本人经办" in response.json()["detail"]
        db_session.refresh(record)
        assert record.status == before
        assert rec.status == "CONFIRMED"


def test_builtin_buyer_replenishment_flow_and_foreign_request_scope(client: TestClient, db_session) -> None:
    """默认采购员可办理本人补货，不能审批或借本人订单完成他人补货。"""
    from app.modules.purchase_orders.model import PurchaseOrder
    from app.modules.replenishments.model import ReplenishmentRequest

    buyer = db_session.scalar(select(User).where(User.username == "buyer"))
    manager = db_session.scalar(select(User).where(User.username == "procurement_manager"))
    template = db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.status == "COMPLETED"))
    assert buyer is not None and manager is not None and template is not None and template.items
    own_order = PurchaseOrder(
        po_no=f"RBAC-RP-{uuid4().hex[:12]}", supplier_id=template.supplier_id,
        buyer_id=buyer.id, department_id=buyer.department_id, status="ORDERED",
    )
    foreign = ReplenishmentRequest(
        replenishment_no=f"RBAC-RP-{uuid4().hex[:12]}", supplier_id=template.supplier_id,
        applicant_id=manager.id, reason="他人补货", status="APPROVED",
    )
    db_session.add_all((own_order, foreign))
    db_session.flush()
    with as_demo_role(db_session, "BUYER"):
        created = client.post("/api/v1/replenishments", json={
            "supplier_id": template.supplier_id, "source_po_id": own_order.id,
            "reason": "采购员本人补货", "items": [{
                "product_id": template.items[0].product_id,
                "unit_id": template.items[0].unit_id, "requested_quantity": "1",
            }],
        })
        assert created.status_code == 201, created.text
        own_id = created.json()["id"]
        listed = client.get("/api/v1/replenishments", params={"page_size": 100}).json()
        expected_ids = set(db_session.scalars(select(ReplenishmentRequest.id).where(
            ReplenishmentRequest.applicant_id == buyer.id
        )))
        assert listed["total"] == len(expected_ids)
        assert {row["id"] for row in listed["items"]} == expected_ids
        assert client.get(f"/api/v1/replenishments/{own_id}").status_code == 200
        assert client.get(f"/api/v1/replenishments/{foreign.id}").status_code == 404
        for action, body in (("submit", None), ("cancel", None), ("complete", {"fulfillment_po_id": own_order.id})):
            refused = client.post(f"/api/v1/replenishments/{foreign.id}/{action}", json=body)
            assert refused.status_code == 404, refused.text
        assert client.post(f"/api/v1/replenishments/{own_id}/submit").status_code == 200
        for action, body in (("approve", None), ("reject", {"reason": "越权驳回"})):
            assert client.post(f"/api/v1/replenishments/{own_id}/{action}", json=body).status_code == 403
    with as_demo_role(db_session, "PROCUREMENT_MANAGER"):
        assert client.post(f"/api/v1/replenishments/{own_id}/approve").status_code == 200
    with as_demo_role(db_session, "BUYER"):
        completed = client.post(f"/api/v1/replenishments/{own_id}/complete", json={"fulfillment_po_id": own_order.id})
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "COMPLETED"
    db_session.refresh(foreign)
    assert foreign.status == "APPROVED" and foreign.fulfillment_po_id is None


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


def test_buyer_cannot_move_or_create_requests_outside_department_or_link_them_to_rfq(
    client: TestClient, db_session
) -> None:
    buyer = db_session.scalar(select(User).where(User.username == "buyer", User.status == "ACTIVE"))
    assert buyer is not None
    suffix = uuid4().hex[:10]
    own_department = Department(
        department_code=f"RBAC-OWN-{suffix}", department_name="申请人部门", status="ACTIVE",
    )
    other_department = Department(
        department_code=f"RBAC-FOREIGN-{suffix}", department_name="其他部门", status="ACTIVE",
    )
    db_session.add_all((own_department, other_department))
    db_session.flush()
    buyer.department_id = own_department.id
    own_request = PurchaseRequest(
        request_no=f"RBAC-OWN-{suffix}", applicant_id=buyer.id,
        department_id=own_department.id, purpose="本人部门申请", status="DRAFT",
    )
    foreign_request = PurchaseRequest(
        request_no=f"RBAC-FOREIGN-{suffix}", applicant_id=buyer.id,
        department_id=other_department.id, purpose="跨部门申请", status="APPROVED",
    )
    db_session.add_all((own_request, foreign_request))
    db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: buyer
    try:
        created = client.post(
            "/api/v1/purchase-requests",
            json={
                "department_id": other_department.id,
                "purpose": "跨部门创建",
                "items": [{"requested_name": "测试物料", "quantity": 1, "unit_id": 1}],
            },
        )
        moved = client.patch(
            f"/api/v1/purchase-requests/{own_request.id}",
            json={"department_id": other_department.id},
        )
        linked = client.post(
            "/api/v1/rfqs",
            json={
                "source_request_id": foreign_request.id,
                "items": [{
                    "source_request_item_id": 1, "requested_name": "跨部门明细",
                    "quantity": 1, "unit_id": 1,
                }],
                "supplier_ids": [1],
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert created.status_code == 404
    assert moved.status_code == 404
    assert linked.status_code == 404
    db_session.refresh(own_request)
    assert own_request.department_id == own_department.id


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


def test_quality_inspector_lists_and_reads_only_assigned_acceptances(
    client: TestClient, db_session
) -> None:
    inspector = db_session.scalar(
        select(User).where(User.username == "quality_inspector", User.status == "ACTIVE")
    )
    role = db_session.scalar(select(Role).where(Role.role_code == "QUALITY"))
    acceptance = db_session.scalar(select(QualityAcceptance).order_by(QualityAcceptance.id))
    assert inspector is not None and role is not None and acceptance is not None

    acceptance.inspector_id = inspector.id
    other = User(
        username=f"quality-other-{uuid4().hex[:10]}", password_hash="unused-test-hash",
        display_name="其他质量检验员", status="ACTIVE",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(UserRole(user_id=other.id, role_id=role.id))
    db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: other
    try:
        listed = client.get("/api/v1/quality-acceptances", params={"page_size": 100})
        detail = client.get(f"/api/v1/quality-acceptances/{acceptance.id}")
        reports = client.get(f"/api/v1/quality-acceptances/{acceptance.id}/report-files")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert listed.status_code == 200
    assert listed.json()["total"] == 0
    assert listed.json()["items"] == []
    assert detail.status_code == 404
    assert reports.status_code == 404


def test_quality_manager_assigns_acceptance_and_inspector_cannot_self_assign(client: TestClient, db_session) -> None:
    from app.modules.deliveries.model import Delivery
    from app.modules.purchase_orders.model import PurchaseOrder

    inspector = db_session.scalar(select(User).where(User.username == "quality_inspector"))
    buyer = db_session.scalar(select(User).where(User.username == "buyer"))
    template = db_session.scalar(select(PurchaseOrder))
    assert inspector is not None and buyer is not None and template is not None
    delivery = Delivery(delivery_no=f"RBAC-QA-{uuid4().hex[:12]}", po_id=template.id,
                        supplier_id=template.supplier_id, status="RECEIVED")
    db_session.add(delivery)
    db_session.flush()
    body = {"delivery_id": delivery.id, "inspector_id": inspector.id}
    before = db_session.scalar(select(func.count(QualityAcceptance.id)))
    with as_demo_role(db_session, "QUALITY"):
        assert client.get("/api/v1/quality-acceptances/assignment-options").status_code == 403
        assert client.post("/api/v1/quality-acceptances", json=body).status_code == 403
    with as_demo_role(db_session, "QUALITY_MANAGER"):
        options = client.get("/api/v1/quality-acceptances/assignment-options")
        assert options.status_code == 200, options.text
        assert delivery.id in {row["id"] for row in options.json()["deliveries"]}
        assert inspector.id in {row["id"] for row in options.json()["inspectors"]}
        assert buyer.id not in {row["id"] for row in options.json()["inspectors"]}
        assert all(set(row) == {"id", "delivery_no"} for row in options.json()["deliveries"])
        assert all(set(row) == {"id", "username", "display_name"} for row in options.json()["inspectors"])
        assert client.post("/api/v1/quality-acceptances", json={"delivery_id": delivery.id}).status_code == 422
        refused = client.post("/api/v1/quality-acceptances", json={**body, "inspector_id": buyer.id})
        assert refused.status_code == 400, refused.text
        inspector.status = "INACTIVE"
        db_session.flush()
        assert client.post("/api/v1/quality-acceptances", json=body).status_code == 400
        db_session.refresh(delivery)
        assert delivery.status == "RECEIVED"
        assert db_session.scalar(select(func.count(QualityAcceptance.id))) == before
        inspector.status = "ACTIVE"
        db_session.flush()
        created = client.post("/api/v1/quality-acceptances", json=body)
        assert created.status_code == 201, created.text
        assert created.json()["inspector_id"] == inspector.id
        acceptance_id = created.json()["id"]
    with as_demo_role(db_session, "QUALITY"):
        detail = client.get(f"/api/v1/quality-acceptances/{acceptance_id}")
        assert detail.status_code == 200, detail.text
        assert client.get(f"/api/v1/quality-acceptances/{acceptance_id}/report-files").status_code == 200
        listed = client.get("/api/v1/quality-acceptances", params={"page_size": 100})
        assert listed.status_code == 200
        expected = set(db_session.scalars(select(QualityAcceptance.id).where(QualityAcceptance.inspector_id == inspector.id)))
        assert listed.json()["total"] == len(expected)
    db_session.refresh(delivery)
    assert delivery.status == "INSPECTING"


def test_warehouse_exception_scope_follows_inventory_and_task_assignment(
    client: TestClient, db_session
) -> None:
    warehouse_role = db_session.scalar(select(Role).where(Role.role_code == "WAREHOUSE"))
    user = db_session.scalar(
        select(User).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == warehouse_role.id, User.status == "ACTIVE")
        .order_by(User.id)
    )
    other_user = db_session.scalar(select(User).where(User.status == "ACTIVE", User.id != user.id).order_by(User.id))
    source = db_session.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).order_by(InventoryBalance.id))
    assert warehouse_role is not None and user is not None and other_user is not None and source is not None

    own_warehouse = Warehouse(
        warehouse_code=f"EX-OWN-{user.id}", warehouse_name="异常范围本人仓库",
        manager_id=user.id, status="ACTIVE",
    )
    foreign_warehouse = Warehouse(
        warehouse_code=f"EX-OTHER-{user.id}", warehouse_name="异常范围其他仓库",
        manager_id=other_user.id, status="ACTIVE",
    )
    db_session.add_all((own_warehouse, foreign_warehouse))
    db_session.flush()
    own_location = WarehouseLocation(
        warehouse_id=own_warehouse.id, location_code=f"EX-OWN-{user.id}",
        location_name="本人库位", status="ACTIVE",
    )
    foreign_location = WarehouseLocation(
        warehouse_id=foreign_warehouse.id, location_code=f"EX-OTHER-{user.id}",
        location_name="其他库位", status="ACTIVE",
    )
    own_batch = InventoryBatch(
        product_id=source.product_id, batch_no=f"EX-OWN-{user.id}", status="ACTIVE",
    )
    foreign_batch = InventoryBatch(
        product_id=source.product_id, batch_no=f"EX-OTHER-{user.id}", status="ACTIVE",
    )
    db_session.add_all((own_location, foreign_location, own_batch, foreign_batch))
    db_session.flush()
    db_session.add_all((
        InventoryBalance(
            warehouse_id=own_warehouse.id, location_id=own_location.id,
            product_id=source.product_id, batch_id=own_batch.id, unit_id=source.unit_id,
            quantity=1, locked_quantity=0, status="AVAILABLE",
        ),
        InventoryBalance(
            warehouse_id=foreign_warehouse.id, location_id=foreign_location.id,
            product_id=source.product_id, batch_id=foreign_batch.id, unit_id=source.unit_id,
            quantity=1, locked_quantity=0, status="AVAILABLE",
        ),
    ))
    own_exception = OperationException(
        exception_no=f"EX-SCOPE-OWN-{user.id}", exception_type="INVENTORY_EXPIRY",
        source_type="INVENTORY_BATCH", source_id=own_batch.id,
        severity="MEDIUM", description="本人授权仓库来源", status="OPEN",
    )
    foreign_exception = OperationException(
        exception_no=f"EX-SCOPE-OTHER-{user.id}", exception_type="INVENTORY_EXPIRY",
        source_type="INVENTORY_BATCH", source_id=foreign_batch.id,
        severity="MEDIUM", description="其他仓库来源", status="OPEN",
    )
    assigned_exception = OperationException(
        exception_no=f"EX-SCOPE-TASK-{user.id}", exception_type="OTHER",
        source_type="OTHER", source_id=987654321, owner_id=other_user.id,
        severity="LOW", description="仅通过处理任务访问", status="OPEN",
    )
    db_session.add_all((own_exception, foreign_exception, assigned_exception))
    db_session.flush()
    assigned_task = OperationTask(
        exception_id=assigned_exception.id, title="本人被指派任务", assignee_id=user.id,
        priority="NORMAL", status="OPEN",
    )
    unrelated_task = OperationTask(
        exception_id=assigned_exception.id, title="其他经办任务", assignee_id=other_user.id,
        priority="NORMAL", status="OPEN",
    )
    db_session.add_all((assigned_task, unrelated_task))
    db_session.flush()

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        listed = client.get("/api/v1/operation-exceptions", params={"page_size": 100})
        own_detail = client.get(f"/api/v1/operation-exceptions/{own_exception.id}")
        foreign_detail = client.get(f"/api/v1/operation-exceptions/{foreign_exception.id}")
        assigned_detail = client.get(f"/api/v1/operation-exceptions/{assigned_exception.id}")
        tasks = client.get(f"/api/v1/operation-exceptions/{assigned_exception.id}/tasks")
        unrelated_task_detail = client.get(
            f"/api/v1/operation-exceptions/{assigned_exception.id}/tasks/{unrelated_task.id}"
        )
        candidates = client.get("/api/v1/operation-exceptions/assignees")
        foreign_source_create = client.post("/api/v1/operation-exceptions", json={
            "exception_type": "INVENTORY_EXPIRY",
            "source_type": "INVENTORY_BATCH",
            "source_id": foreign_batch.id,
            "severity": "MEDIUM",
            "description": "不允许引用其他仓库库存来源",
        })
        create_unrelated_task = client.post(
            f"/api/v1/operation-exceptions/{assigned_exception.id}/tasks",
            json={"title": "不能从被指派任务扩展异常管理权"},
        )
        task_count_before = db_session.scalar(select(func.count(OperationTask.id)))
        adopt_unrelated_action = client.post(
            f"/api/v1/insights/exception-action/{assigned_exception.id}/decision",
            json={"decision": "ADOPTED", "reason": "不能借 AI 扩大异常管理范围"},
        )
        assert db_session.scalar(select(func.count(OperationTask.id))) == task_count_before
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert listed.status_code == 200
    listed_ids = {item["id"] for item in listed.json()["items"]}
    assert own_exception.id in listed_ids
    assert foreign_exception.id not in listed_ids
    assert assigned_exception.id in listed_ids
    assert own_detail.status_code == 200
    assert foreign_detail.status_code == 404
    assert assigned_detail.status_code == 200
    assert tasks.status_code == 200
    assert tasks.json()["total"] == 1
    assert [item["id"] for item in tasks.json()["items"]] == [assigned_task.id]
    assert unrelated_task_detail.status_code == 404
    assert candidates.status_code == 200
    assert user.id in {item["id"] for item in candidates.json()}
    assert foreign_source_create.status_code == 404
    assert create_unrelated_task.status_code == 404
    assert adopt_unrelated_action.status_code == 404, adopt_unrelated_action.text


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


def test_user_role_membership_change_increments_token_version(db_session: Session) -> None:
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    supplier_role = db_session.scalar(select(Role).where(Role.role_code == "SUPPLIER_PORTAL"))
    assert user is not None and supplier_role is not None
    previous_version = user.token_version

    system_service.update_user(db_session, user.id, UserUpdate(role_ids=[supplier_role.id]))

    assert user.token_version == previous_version + 1


def test_role_permission_change_increments_member_token_versions(db_session: Session) -> None:
    role = db_session.scalar(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(Role.role_code != "SYS_ADMIN")
        .order_by(Role.id)
    )
    assert role is not None
    member_ids = list(db_session.scalars(select(UserRole.user_id).where(UserRole.role_id == role.id)).all())
    assert member_ids
    previous_versions = {
        user.id: user.token_version
        for user in db_session.scalars(select(User).where(User.id.in_(member_ids))).all()
    }
    permission_ids = list(
        db_session.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == role.id)).all()
    )
    assert permission_ids

    system_service.update_role(
        db_session,
        role.id,
        RoleUpdate(permission_ids=permission_ids[:-1]),
    )

    db_session.expire_all()
    for user_id, previous_version in previous_versions.items():
        user = db_session.get(User, user_id)
        assert user is not None
        assert user.token_version == previous_version + 1
