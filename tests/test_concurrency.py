"""库存并发扣减测试。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.db import SessionLocal
from app.core.errors import BusinessValidationError
from app.modules.inventory import service
from app.modules.inventory.model import (
    InventoryBalance,
    InventoryBatch,
    InventoryIssueItem,
    InventoryIssueRequest,
    InventoryTransaction,
    Warehouse,
    WarehouseLocation,
)
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.system.audit import AuditLog
from app.modules.system.model import User


pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


def test_two_issue_requests_cannot_overdraw_same_balance(db_engine) -> None:
    """两个独立会话同时出库时，库存行锁应阻止超额扣减。"""

    setup = SessionLocal()
    issue_ids: list[int] = []
    balance_id: int | None = None
    batch_id: int | None = None
    opening_transaction_id: int | None = None
    cost_layer_id: int | None = None
    quantity = Decimal("5.000001")
    try:
        product = setup.scalar(select(Product).where(Product.status == "ACTIVE").order_by(Product.id).limit(1))
        warehouse = setup.scalar(select(Warehouse).where(Warehouse.status == "ACTIVE").order_by(Warehouse.id).limit(1))
        applicant = setup.scalar(select(User).where(User.username == "warehouse_receiver"))
        approver = setup.scalar(select(User).where(User.username == "procurement_manager"))
        unit = setup.get(Unit, product.unit_id) if product is not None else None
        location = (
            setup.scalar(
                select(WarehouseLocation)
                .where(WarehouseLocation.warehouse_id == warehouse.id, WarehouseLocation.status == "ACTIVE")
                .order_by(WarehouseLocation.id)
                .limit(1)
            )
            if warehouse is not None
            else None
        )
        if any(item is None for item in (product, warehouse, location, unit, applicant, approver)):
            message = "并发测试需要启用的产品、仓库、库位、计量单位和演示账号"
            if os.environ.get("CI", "").strip().lower() == "true":
                pytest.fail(message)
            pytest.skip(message)

        opening_quantity = Decimal("10")
        batch = InventoryBatch(product_id=product.id, batch_no=f"CONC-{uuid4().hex[:16]}", status="ACTIVE")
        setup.add(batch)
        setup.flush()
        opening_transaction = InventoryTransaction(
            transaction_no=f"CTI{uuid4().hex[:20]}",
            transaction_type="INBOUND",
            warehouse_id=warehouse.id,
            location_id=location.id,
            product_id=product.id,
            batch_id=batch.id,
            unit_id=unit.id,
            quantity=opening_quantity,
            source_type="TEST_FIXTURE",
            operator_id=approver.id,
            note="并发测试隔离库存",
        )
        setup.add(opening_transaction)
        setup.flush()
        balance = InventoryBalance(
            warehouse_id=warehouse.id,
            location_id=location.id,
            product_id=product.id,
            batch_id=batch.id,
            unit_id=unit.id,
            quantity=opening_quantity,
            locked_quantity=Decimal("0"),
            status="AVAILABLE",
        )
        setup.add(balance)
        cost_layer = InventoryCostLayer(
            source_transaction_id=opening_transaction.id,
            warehouse_id=warehouse.id,
            location_id=location.id,
            product_id=product.id,
            batch_id=batch.id,
            unit_id=unit.id,
            unit_cost=Decimal("1"),
            currency_code="CNY",
            original_quantity=opening_quantity,
            remaining_quantity=opening_quantity,
        )
        setup.add(cost_layer)
        setup.flush()
        balance_id = balance.id
        batch_id = batch.id
        opening_transaction_id = opening_transaction.id
        cost_layer_id = cost_layer.id
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
            if balance_id is not None:
                cleanup.execute(delete(InventoryBalance).where(InventoryBalance.id == balance_id))
            if cost_layer_id is not None:
                cleanup.execute(delete(InventoryCostLayer).where(InventoryCostLayer.id == cost_layer_id))
            if opening_transaction_id is not None:
                cleanup.execute(delete(InventoryTransaction).where(InventoryTransaction.id == opening_transaction_id))
            if batch_id is not None:
                cleanup.execute(delete(InventoryBatch).where(InventoryBatch.id == batch_id))
            cleanup.commit()
        finally:
            cleanup.close()
