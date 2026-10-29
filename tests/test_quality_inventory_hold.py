from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.errors import BusinessValidationError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.inventory.model import (InventoryBalance, InventoryBatch, Warehouse, WarehouseLocation,
    InventoryTransferRequest, InventoryTransferItem, InventoryStocktakeRequest, InventoryStocktakeItem)
from app.modules.inventory.schema import InboundCreate, InventoryBalanceStatusChange
from app.modules.inventory import service as inventory
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.quality_acceptances.schema import QualityAcceptanceResult
from app.modules.quality_acceptances import service as quality
from app.modules.system.model import User


def test_reinspection_blocks_batch_and_preserves_manual_freeze(db_session, monkeypatch):
    item = db_session.scalar(select(PurchaseOrderItem).limit(1))
    order = db_session.get(PurchaseOrder, item.po_id)
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(1))
    location = WarehouseLocation(warehouse_id=warehouse.id, location_code=f'T-{uuid4().hex[:12]}', location_name='测试', status='ACTIVE')
    delivery = Delivery(delivery_no=f'T-{uuid4().hex[:12]}', po_id=order.id, supplier_id=order.supplier_id, status='ACCEPTED')
    delivery.items = [DeliveryItem(line_no=1, product_id=item.product_id, po_item_id=item.id,
        planned_quantity=1, actual_quantity=1, short_quantity=0, unit_id=item.unit_id)]
    db_session.add_all([location, delivery])
    db_session.flush()
    acceptance = QualityAcceptance(acceptance_no=f'T-{uuid4().hex[:12]}', delivery_id=delivery.id,
        inspector_id=admin.id, result='PASSED', certificate_complete=1)
    db_session.add(acceptance)
    db_session.flush()
    _, balances = inventory.create_inbound(db_session, admin, InboundCreate(delivery_id=delivery.id,
        warehouse_id=warehouse.id, location_id=location.id))
    balance = balances[0]
    inventory.freeze_balance(db_session, admin, balance.id, InventoryBalanceStatusChange(reason='人工冻结'))
    quality.submit_result(db_session, admin, acceptance.id, QualityAcceptanceResult(result='REINSPECTION'))
    batch = db_session.get(InventoryBatch, balance.batch_id)
    assert batch.status == 'QUALITY_HOLD'
    assert balance.status == 'FROZEN'
    with pytest.raises(BusinessValidationError, match='质量'):
        inventory.lock_available_batches(db_session, [batch.id])
    batch.status = 'ACTIVE'  # 模拟修复前已处于复检状态的历史记录。
    db_session.flush()
    with pytest.raises(BusinessValidationError, match='质量'):
        inventory.lock_available_batches(db_session, [batch.id])
    batch.status = 'QUALITY_HOLD'
    db_session.flush()
    target = WarehouseLocation(warehouse_id=warehouse.id, location_code=f'T-{uuid4().hex[:12]}', location_name='目标', status='ACTIVE')
    db_session.add(target)
    db_session.flush()
    transfer = InventoryTransferRequest(transfer_no=f'T-{uuid4().hex[:12]}', applicant_id=admin.id, purpose='测试', status='APPROVED')
    transfer.items = [InventoryTransferItem(line_no=1, product_id=item.product_id,
        source_warehouse_id=warehouse.id, source_location_id=location.id, target_warehouse_id=warehouse.id,
        target_location_id=target.id, batch_id=batch.id, unit_id=item.unit_id, requested_quantity=1)]
    stocktake = InventoryStocktakeRequest(stocktake_no=f'T-{uuid4().hex[:12]}', applicant_id=admin.id,
        warehouse_id=warehouse.id, purpose='测试', status='APPROVED')
    stocktake.items = [InventoryStocktakeItem(line_no=1, product_id=item.product_id, location_id=target.id,
        batch_id=batch.id, unit_id=item.unit_id, book_quantity=0, counted_quantity=1)]
    db_session.add_all([transfer, stocktake])
    db_session.flush()
    # 履约服务会主动回滚错误；此测试在隔离的外层回滚事务内验证，避免丢失样本。
    with monkeypatch.context() as patcher:
        from app.modules.inventory_cost.schema import FifoOutboundCreate
        from app.modules.inventory_cost.service import create_fifo_outbound
        patcher.setattr(db_session, 'rollback', lambda: None)
        with pytest.raises(BusinessValidationError, match='质量'):
            inventory.execute_transfer_request(db_session, admin, transfer.id)
        with pytest.raises(BusinessValidationError, match='质量'):
            inventory.execute_stocktake_request(db_session, admin, stocktake.id)
        with pytest.raises(BusinessValidationError, match='质量'):
            create_fifo_outbound(db_session, admin, FifoOutboundCreate(request_no=f'T-{uuid4().hex[:12]}',
                product_id=item.product_id, warehouse_id=warehouse.id, location_id=location.id,
                unit_id=item.unit_id, quantity=1))
    assert db_session.scalar(select(InventoryBalance.id).where(
        InventoryBalance.batch_id == batch.id, InventoryBalance.location_id == target.id)) is None
    quality.submit_result(db_session, admin, acceptance.id, QualityAcceptanceResult(result='FAILED'))
    assert batch.status == 'QUALITY_HOLD'
    quality.submit_result(db_session, admin, acceptance.id, QualityAcceptanceResult(result='REINSPECTION'))
    quality.submit_result(db_session, admin, acceptance.id, QualityAcceptanceResult(result='PASSED'))
    assert batch.status == 'ACTIVE'
    assert balance.status == 'FROZEN'


def test_quality_hold_blocks_inventory_operations(db_session):
    # The workflow above creates an independent fixture; this test exercises the
    # batch guard with a previously quarantined batch without writing stock.
    batch = db_session.scalar(select(InventoryBatch).limit(1))
    batch.status = 'QUALITY_HOLD'
    db_session.flush()
    with pytest.raises(BusinessValidationError, match='质量'):
        inventory.lock_available_batches(db_session, [batch.id])


def test_inventory_batch_lock_waits_for_quality_transaction(db_engine):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    from sqlalchemy.orm import Session

    with Session(db_engine) as owner:
        batch = owner.scalar(select(InventoryBatch).where(InventoryBatch.status == 'ACTIVE').limit(1).with_for_update())
        assert batch is not None
        batch_id = batch.id
        batch.status = 'QUALITY_HOLD'
        owner.flush()
        started = Event()
        def lock_for_inventory():
            with Session(db_engine) as other:
                started.set()
                inventory.lock_available_batches(other, [batch_id])
                other.rollback()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lock_for_inventory)
            assert started.wait(5)
            try:
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.25)
            finally:
                owner.rollback()
            future.result(timeout=10)
