"""正式下单前必须检查来源申请的最新可采购额度。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.core.errors import BusinessValidationError
from app.modules.purchase_orders import service
from app.modules.purchase_requests.model import PurchaseRequestItem
from app.modules.rfqs.model import RFQItem


class PlacementSession:
    def __init__(self, request_item):
        self.request_item = request_item
        self.committed = False

    def scalar(self, statement):
        return SimpleNamespace(rfq_item_id=11)

    def get(self, model, identifier):
        if model is RFQItem:
            return SimpleNamespace(source_request_item_id=21)
        if model is PurchaseRequestItem:
            return self.request_item
        raise AssertionError(model)

    def commit(self):
        self.committed = True

    def scalars(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: [self.request_item])


def test_approved_order_cannot_reuse_fulfilled_request_quantity(monkeypatch):
    item = SimpleNamespace(id=21, quantity=Decimal('10'), fulfilled_quantity=Decimal('10'), status='FULFILLED')
    order = SimpleNamespace(id=1, status='APPROVED', source_request_id=31,
        items=[SimpleNamespace(source_quote_item_id=41, order_quantity=Decimal('10'))])
    db = PlacementSession(item)
    monkeypatch.setattr(service, 'get_order', lambda *args, **kwargs: order)
    monkeypatch.setattr(service, '_add_event', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, '_require_order', lambda *args, **kwargs: order)
    with pytest.raises(BusinessValidationError, match='剩余可采购数量不足'):
        service.place_order(db, SimpleNamespace(id=7), order.id)
    assert order.status == 'APPROVED'
    assert item.fulfilled_quantity == Decimal('10')
    assert not db.committed
    assert 'FOR UPDATE' in str(db.statement.compile(dialect=mysql.dialect()))
    assert db.statement.get_execution_options()['populate_existing'] is True


@pytest.mark.parametrize(('quantities', 'already', 'allowed'), [
    (['3', '4'], '3', True),
    (['3', '4'], '4', False),
])
def test_place_order_checks_sum_of_lines_before_writing(monkeypatch, quantities, already, allowed):
    item = SimpleNamespace(id=21, quantity=Decimal('10'), fulfilled_quantity=Decimal(already), status='PARTIAL')
    order = SimpleNamespace(id=1, status='APPROVED', source_request_id=31,
        items=[SimpleNamespace(source_quote_item_id=41, order_quantity=Decimal(value)) for value in quantities])
    db = PlacementSession(item)
    monkeypatch.setattr(service, 'get_order', lambda *args, **kwargs: order)
    monkeypatch.setattr(service, '_add_event', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, '_require_order', lambda *args, **kwargs: order)
    if not allowed:
        with pytest.raises(BusinessValidationError, match='剩余可采购数量不足'):
            service.place_order(db, SimpleNamespace(id=7), order.id)
        assert item.fulfilled_quantity == Decimal(already)
        assert order.status == 'APPROVED'
        assert not db.committed
    else:
        service.place_order(db, SimpleNamespace(id=7), order.id)
        assert item.fulfilled_quantity == Decimal('10')
        assert item.status == 'FULFILLED'
        assert order.status == 'ORDERED'
        assert db.committed
