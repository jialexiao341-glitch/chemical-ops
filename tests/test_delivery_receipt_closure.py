from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.deliveries import service
from app.modules.deliveries.schema import DeliveryReceive


def test_receipt_rejects_unexplained_quantity(monkeypatch):
    item = SimpleNamespace(id=1, po_item_id=2, line_no=1, planned_quantity=Decimal('10'))
    delivery = SimpleNamespace(id=1, po_id=3, status='IN_TRANSIT', items=[item])
    order_item = SimpleNamespace(id=2, received_quantity=Decimal('0'), order_quantity=Decimal('10'))
    order = SimpleNamespace(items=[order_item], status='ORDERED', events=[])
    monkeypatch.setattr(service, '_require_delivery', lambda *args, **kwargs: delivery)
    monkeypatch.setattr(service, '_require_order', lambda *args, **kwargs: order)
    monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
    data = DeliveryReceive(items=[{'delivery_item_id': 1, 'actual_quantity': '6', 'short_quantity': '0'}])

    with pytest.raises(BusinessValidationError, match='计划数量'):
        service.receive_delivery(SimpleNamespace(commit=lambda: None), SimpleNamespace(id=1), 1, data)

    assert delivery.status == 'IN_TRANSIT'
    assert order_item.received_quantity == 0


def test_delivery_listing_does_not_materialize_visible_orders(db_session):
    from sqlalchemy import event, select
    from app.modules.system.model import User

    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    assert user is not None
    statements = []
    connection = db_session.connection()
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(connection, 'before_cursor_execute', capture)
    try:
        service.list_deliveries(db_session, user, keyword=None, status=None, page=1, page_size=5)
    finally:
        event.remove(connection, 'before_cursor_execute', capture)
    assert not any('select purchase_orders.id, purchase_orders.' in sql for sql in statements)
