"""库存并发扣减测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.core.errors import BusinessValidationError
from app.modules.inventory import service
from app.modules.inventory.model import InventoryBalance, InventoryIssueItem, InventoryIssueRequest, InventoryTransaction
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer
from app.modules.system.audit import AuditLog
from app.modules.system.model import User


pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


def test_two_issue_requests_cannot_overdraw_same_balance(db_engine) -> None:
    """两个独立会话同时出库时，库存行锁应阻止超额扣减。"""

    setup = SessionLocal()
    issue_ids: list[int] = []
    balance_id = None
    quantity = None
    try:
        balance = setup.scalar(select(InventoryBalance).where(InventoryBalance.status == "AVAILABLE", InventoryBalance.quantity > 0).order_by(InventoryBalance.id).limit(1))
        applicant = setup.scalar(select(User).where(User.username == "warehouse_receiver"))
        approver = setup.scalar(select(User).where(User.username == "procurement_manager"))
        if balance is None or applicant is None or approver is None:
            pytest.skip("缺少并发测试所需的可用库存或演示账号")
        balance_id = balance.id
        quantity = (balance.quantity / Decimal("2")) + Decimal("0.000001")
        for suffix in ("A", "B"):
            issue = InventoryIssueRequest(
                issue_no=f"CONCURRENCY-{uuid4().hex[:12]}-{suffix}",
                applicant_id=applicant.id,
                purpose="并发扣减测试",
                status="APPROVED",
                approved_by=approver.id,
                approved_at=datetime.now(timezone.utc),
            )
            setup.add(issue)
            setup.flush()
            issue.issue_no = f"CT{datetime.now():%Y%m%d%H%M%S}{issue.id:06d}{suffix}"
            setup.add(InventoryIssueItem(
                issue_request_id=issue.id,
                line_no=1,
                product_id=balance.product_id,
                warehouse_id=balance.warehouse_id,
                location_id=balance.location_id,
                batch_id=balance.batch_id,
                unit_id=balance.unit_id,
                requested_quantity=quantity,
            ))
            issue_ids.append(issue.id)
        setup.commit()
    finally:
        setup.close()

    barrier = Barrier(2)

    def execute(issue_id: int) -> str:
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.username == "warehouse_receiver"))
            barrier.wait(timeout=10)
            service.execute_issue_request(db, user, issue_id)
            return "success"
        except BusinessValidationError:
            return "business_error"
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(execute, issue_ids))
        assert sorted(results) == ["business_error", "success"]
    finally:
        cleanup = SessionLocal()
        try:
            outbound_count = cleanup.scalar(
                select(func.count(InventoryTransaction.id)).where(
                    InventoryTransaction.source_type == "ISSUE_REQUEST",
                    InventoryTransaction.source_id.in_(issue_ids),
                    InventoryTransaction.transaction_type == "OUTBOUND",
                )
            ) or 0
            allocations = list(cleanup.scalars(
                select(InventoryCostAllocation).join(
                    InventoryTransaction,
                    InventoryTransaction.id == InventoryCostAllocation.transaction_id,
                ).where(
                    InventoryTransaction.source_type == "ISSUE_REQUEST",
                    InventoryTransaction.source_id.in_(issue_ids),
                )
            ).all())
            for allocation in allocations:
                layer = cleanup.get(InventoryCostLayer, allocation.cost_layer_id)
                if layer is not None:
                    layer.remaining_quantity += allocation.quantity
            balance = cleanup.get(InventoryBalance, balance_id) if balance_id is not None else None
            if balance is not None:
                balance.quantity += quantity * outbound_count
            cleanup.execute(delete(InventoryCostAllocation).where(InventoryCostAllocation.id.in_([item.id for item in allocations])))
            cleanup.execute(delete(InventoryTransaction).where(InventoryTransaction.source_type == "ISSUE_REQUEST", InventoryTransaction.source_id.in_(issue_ids)))
            cleanup.execute(delete(AuditLog).where(AuditLog.resource_type == "INVENTORY_ISSUE_REQUEST", AuditLog.resource_id.in_(issue_ids)))
            cleanup.execute(delete(InventoryIssueItem).where(InventoryIssueItem.issue_request_id.in_(issue_ids)))
            cleanup.execute(delete(InventoryIssueRequest).where(InventoryIssueRequest.id.in_(issue_ids)))
            cleanup.commit()
        finally:
            cleanup.close()
