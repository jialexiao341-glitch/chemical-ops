"""问题清单第一批整改：真实数据库事务内验证数据与授权边界。"""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, InventoryStocktakeRequest, InventoryStocktakeItem
from app.modules.inventory_cost.model import InventoryCostLayer
from app.modules.inventory_cost.service import allocate_outbound_cost, adjust_stocktake_cost
from app.modules.inventory import service as inventory_service
from app.modules.system import service as system_service
from app.modules.system.model import Role, User
from app.modules.system.audit import AuditLog
from app.modules.system.schema import UserUpdate, UserCreate
from app.modules.files import service as file_service



def stock_fixture(db):
    source = db.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).limit(1))
    actor = db.scalar(select(User).where(User.username == "system_admin"))
    assert source is not None and actor is not None
    batch = InventoryBatch(product_id=source.product_id, batch_no=f"REMED-{uuid4().hex[:12]}")
    db.add(batch)
    db.flush()
    slot = dict(product_id=source.product_id, warehouse_id=source.warehouse_id,
                location_id=source.location_id, unit_id=source.unit_id, batch_id=batch.id)
    return actor, slot


def transaction(db, actor, slot, quantity="10"):
    tx = InventoryTransaction(**slot, transaction_no=f"RT-{uuid4().hex[:20]}",
                              transaction_type="ADJUSTMENT", quantity=Decimal(quantity), operator_id=actor.id)
    db.add(tx)
    db.flush()
    return tx


def layer(db, actor, slot, quantity="10", cost="8"):
    tx = transaction(db, actor, slot, quantity)
    value = InventoryCostLayer(**slot, source_transaction_id=tx.id, original_quantity=Decimal(quantity),
                               remaining_quantity=Decimal(quantity), unit_cost=Decimal(cost), currency_code="CNY")
    db.add(value)
    db.flush()
    return value


def test_outbound_never_consumes_another_batch(db_session):
    actor, slot = stock_fixture(db_session)
    own = layer(db_session, actor, slot, cost="9")
    other_batch = InventoryBatch(product_id=slot["product_id"], batch_no=f"OTHER-{uuid4().hex[:12]}")
    db_session.add(other_batch)
    db_session.flush()
    other = layer(db_session, actor, {**slot, "batch_id": other_batch.id}, cost="2")
    tx = transaction(db_session, actor, {**slot, "batch_id": other_batch.id}, "3")
    assert allocate_outbound_cost(db_session, tx, Decimal("3")) == Decimal("6")
    assert other.remaining_quantity == Decimal("7")
    assert own.remaining_quantity == Decimal("10")
    with pytest.raises(BusinessValidationError, match="成本层不足"):
        allocate_outbound_cost(db_session, tx, Decimal("8"))


@pytest.mark.parametrize("counted", ["7", "13"])
def test_stocktake_keeps_cost_quantity_equal_to_balance(db_session, counted):
    actor, slot = stock_fixture(db_session)
    balance = InventoryBalance(**slot, quantity=Decimal("10"), locked_quantity=0, status="AVAILABLE")
    db_session.add(balance)
    layer(db_session, actor, slot, quantity="4", cost="5")
    layer(db_session, actor, slot, quantity="6", cost="7")
    request = InventoryStocktakeRequest(stocktake_no=f"ST-R-{uuid4().hex[:12]}", applicant_id=actor.id,
        warehouse_id=slot["warehouse_id"], location_id=slot["location_id"], purpose="成本盘点回归", status="APPROVED")
    request.items.append(InventoryStocktakeItem(line_no=1, product_id=slot["product_id"],
        location_id=slot["location_id"], batch_id=slot["batch_id"], unit_id=slot["unit_id"],
        book_quantity=Decimal("10"), counted_quantity=Decimal(counted), difference_quantity=0, status="PENDING"))
    db_session.add(request)
    db_session.flush()
    inventory_service.execute_stocktake_request(db_session, actor, request.id)
    cost_quantity = db_session.scalar(select(func.sum(InventoryCostLayer.remaining_quantity)).where(InventoryCostLayer.batch_id == slot["batch_id"]))
    assert cost_quantity == balance.quantity == Decimal(counted)
    if counted == "13":
        gain = db_session.scalar(select(InventoryCostLayer).where(InventoryCostLayer.batch_id == slot["batch_id"]).order_by(InventoryCostLayer.id.desc()))
        assert gain.unit_cost == Decimal("6.2")


def test_stocktake_gain_requires_cost_basis(db_session):
    actor, slot = stock_fixture(db_session)
    tx = transaction(db_session, actor, slot)
    with pytest.raises(BusinessValidationError, match="历史成本依据"):
        adjust_stocktake_cost(db_session, tx, Decimal("1"))


def test_historical_return_cost_repair_is_audited_and_idempotent(db_session):
    from scripts.repair_return_cost_batches import repair
    from app.modules.inventory_cost.model import InventoryCostAllocation
    actor, source = stock_fixture(db_session)
    wrong = layer(db_session, actor, source, cost="8")
    other_batch = InventoryBatch(product_id=source["product_id"], batch_no=f"REPAIR-{uuid4().hex[:12]}")
    db_session.add(other_batch); db_session.flush()
    target = {**source, "batch_id": other_batch.id}
    correct = layer(db_session, actor, target, cost="3")
    db_session.add_all([InventoryBalance(**source, quantity=10, locked_quantity=0, status="AVAILABLE"),
                       InventoryBalance(**target, quantity=8, locked_quantity=0, status="AVAILABLE")])
    tx = transaction(db_session, actor, target, "2")
    tx.source_type = "INVENTORY_RETURN"
    wrong.remaining_quantity = Decimal("8")
    allocation = InventoryCostAllocation(transaction_id=tx.id, cost_layer_id=wrong.id, quantity=2, unit_cost=8, total_cost=16)
    db_session.add(allocation); db_session.flush()
    reports = repair(db_session, actor.id)
    own = next(row for row in reports if row["transaction_id"] == tx.id)
    assert Decimal(own["new_cost"]) == 6
    assert allocation.cost_layer_id == correct.id
    assert wrong.remaining_quantity == 10 and correct.remaining_quantity == 8
    assert repair(db_session, actor.id) == []
    assert db_session.scalar(select(AuditLog.id).where(AuditLog.action_type == "REPAIR_COST_ALLOCATION", AuditLog.resource_id == tx.id)) is not None
