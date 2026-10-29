from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.inventory_cost.service import allocate_outbound_cost


class CostSession:
    def __init__(self, layers):
        self.layers = layers
        self.allocations = []

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: self.layers)

    def add(self, value):
        self.allocations.append(value)


def layer(layer_id, currency, quantity, price):
    return SimpleNamespace(id=layer_id, currency_code=currency,
                           remaining_quantity=Decimal(quantity), unit_cost=Decimal(price))


def transaction():
    return SimpleNamespace(id=7, product_id=1, warehouse_id=1, location_id=1, unit_id=1, batch_id=1)


def test_outbound_allocation_returns_original_currency():
    session = CostSession([layer(1, 'USD', '3', '2')])
    cost, currency = allocate_outbound_cost(session, transaction(), Decimal('2'))
    assert (cost, currency) == (Decimal('4'), 'USD')
    assert session.layers[0].remaining_quantity == Decimal('1')


def test_outbound_rejects_mixed_currencies_before_deducting():
    session = CostSession([layer(1, 'USD', '1', '2'), layer(2, 'CNY', '1', '3')])
    with pytest.raises(BusinessValidationError, match='币种'):
        allocate_outbound_cost(session, transaction(), Decimal('2'))
    assert [item.remaining_quantity for item in session.layers] == [Decimal('1'), Decimal('1')]
    assert not session.allocations


@pytest.mark.parametrize('currencies, quantity, expected', [
    (('USD', 'USD'), '2', 'USD'),
    (('USD', 'CNY'), '2', None),
    (('USD', 'CNY'), '1', 'USD'),
])
def test_fifo_outbound_preserves_currency_or_rejects_mixed(db_session, currencies, quantity, expected):
    from uuid import uuid4
    from sqlalchemy import select
    from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, Warehouse, WarehouseLocation
    from app.modules.inventory_cost.model import InventoryCostLayer
    from app.modules.inventory_cost.schema import FifoOutboundCreate
    from app.modules.inventory_cost.service import create_fifo_outbound
    from app.modules.system.model import User

    batch = db_session.scalar(select(InventoryBatch).limit(1))
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(1))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    assert batch is not None and warehouse is not None and admin is not None
    product_id = batch.product_id
    from app.modules.products.model import Product
    product = db_session.get(Product, product_id)
    assert product is not None and product.status == 'ACTIVE'
    location = WarehouseLocation(warehouse_id=warehouse.id, location_code=f'T-{uuid4().hex[:12]}', location_name='测试', status='ACTIVE')
    db_session.add(location)
    db_session.flush()
    balance = InventoryBalance(warehouse_id=warehouse.id, location_id=location.id, product_id=product.id,
                               batch_id=batch.id, unit_id=product.unit_id, quantity=2, locked_quantity=0, status='AVAILABLE')
    db_session.add(balance)
    for currency in currencies:
        source = InventoryTransaction(transaction_no=f'T-{uuid4().hex[:12]}', transaction_type='INBOUND',
            warehouse_id=warehouse.id, location_id=location.id, product_id=product.id, batch_id=batch.id,
            unit_id=product.unit_id, quantity=1, operator_id=admin.id)
        db_session.add(source)
        db_session.flush()
        db_session.add(InventoryCostLayer(source_transaction_id=source.id, warehouse_id=warehouse.id,
            location_id=location.id, product_id=product.id, batch_id=batch.id, unit_id=product.unit_id,
            unit_cost=2, currency_code=currency, original_quantity=1, remaining_quantity=1))
    db_session.flush()
    request = FifoOutboundCreate(request_no=f'T-{uuid4().hex[:12]}', product_id=product.id,
        warehouse_id=warehouse.id, location_id=location.id, unit_id=product.unit_id, quantity=quantity)
    if expected is None:
        with pytest.raises(BusinessValidationError, match='币种'):
            create_fifo_outbound(db_session, admin, request)
    else:
        result = create_fifo_outbound(db_session, admin, request)
        assert result.currency_code == expected
        assert result.total_cost == Decimal(quantity) * 2


def test_inbound_cost_layer_uses_order_currency(db_session):
    from uuid import uuid4
    from sqlalchemy import select
    from app.modules.deliveries.model import Delivery, DeliveryItem
    from app.modules.inventory.model import Warehouse, WarehouseLocation, InventoryTransferRequest, InventoryTransferItem
    from app.modules.inventory.schema import InboundCreate
    from app.modules.inventory.service import create_inbound, execute_transfer_request
    from app.modules.inventory_cost.model import InventoryCostLayer
    from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
    from app.modules.system.model import User

    order_item = db_session.scalar(select(PurchaseOrderItem).limit(1))
    order = db_session.get(PurchaseOrder, order_item.po_id)
    warehouse = db_session.scalar(select(Warehouse).where(Warehouse.status == 'ACTIVE').limit(1))
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    assert order is not None and warehouse is not None and admin is not None
    order.currency_code = 'USD'
    location = WarehouseLocation(warehouse_id=warehouse.id, location_code=f'T-{uuid4().hex[:12]}', location_name='测试', status='ACTIVE')
    delivery = Delivery(delivery_no=f'T-{uuid4().hex[:12]}', po_id=order.id, supplier_id=order.supplier_id, status='ACCEPTED')
    delivery.items = [DeliveryItem(line_no=1, product_id=order_item.product_id, po_item_id=order_item.id,
        planned_quantity=1, actual_quantity=1, short_quantity=0, unit_id=order_item.unit_id)]
    db_session.add_all([location, delivery])
    db_session.flush()
    transactions, _ = create_inbound(db_session, admin, InboundCreate(delivery_id=delivery.id,
        warehouse_id=warehouse.id, location_id=location.id))
    layer = db_session.scalar(select(InventoryCostLayer).where(InventoryCostLayer.source_transaction_id == transactions[0].id))
    assert layer.currency_code == 'USD'
    target = WarehouseLocation(warehouse_id=warehouse.id, location_code=f'T-{uuid4().hex[:12]}', location_name='目标', status='ACTIVE')
    db_session.add(target)
    db_session.flush()
    transfer = InventoryTransferRequest(transfer_no=f'T-{uuid4().hex[:12]}', applicant_id=admin.id,
        purpose='币种测试', status='APPROVED')
    transfer.items = [InventoryTransferItem(line_no=1, product_id=order_item.product_id,
        source_warehouse_id=warehouse.id, source_location_id=location.id, target_warehouse_id=warehouse.id,
        target_location_id=target.id, batch_id=layer.batch_id, unit_id=order_item.unit_id, requested_quantity=1)]
    db_session.add(transfer)
    db_session.flush()
    execute_transfer_request(db_session, admin, transfer.id)
    target_layer = db_session.scalar(select(InventoryCostLayer).where(InventoryCostLayer.location_id == target.id))
    assert target_layer.currency_code == 'USD'
    assert target_layer.unit_cost == layer.unit_cost
