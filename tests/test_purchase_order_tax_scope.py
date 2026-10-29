"""中选报价税务口径必须传递到采购订单。"""

from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.purchase_orders import service
from app.modules.purchase_orders.schema import PurchaseOrderCreate
from app.modules.finance import reconciliation_items
from app.modules.finance.schema import ReconciliationItemsRefresh
from app.modules.inventory import service as inventory_service


class OrderSession:
    def __init__(self):
        self.order = None

    def scalar(self, statement):
        return None

    def begin_nested(self):
        return nullcontext()

    def add(self, order):
        self.order = order

    def flush(self):
        if self.order is not None:
            self.order.id = 1


@pytest.mark.parametrize(("included", "price", "expected"), [
    (True, "113", "113"),
    (False, "100", "113"),
])
def test_order_preserves_quote_tax_basis(monkeypatch, included, price, expected):
    rfq_item = SimpleNamespace(id=1, line_no=1, product_id=2, requested_name="样品", required_delivery_date=None)
    quote_item = SimpleNamespace(rfq_item_id=1, quoted_quantity=Decimal("1"), unit_price=Decimal(price),
        tax_rate=Decimal("13"), tax_included=included, supplier_product_id=None, supplier_model=None,
        unit_id=1, payment_terms=None, id=3)
    comparison = SimpleNamespace(id=4)
    quote = SimpleNamespace(id=5, supplier_id=6, currency_code="CNY", rfq=SimpleNamespace(source_request_id=7))
    request = SimpleNamespace(department_id=8)
    monkeypatch.setattr(service, "_validate_source", lambda *args: (comparison, quote, request, {1: rfq_item}, {1: quote_item}))
    monkeypatch.setattr(service, "add_audit_log", lambda *args, **kwargs: None)
    order = service.create_order(OrderSession(), SimpleNamespace(id=1), PurchaseOrderCreate(comparison_id=4, quote_id=5), commit=False)
    assert order.order_amount == Decimal(expected)
    assert order.items[0].tax_included is included


def test_order_rejects_unknown_tax_basis(monkeypatch):
    rfq_item = SimpleNamespace(id=1, line_no=1, product_id=2, requested_name="样品", required_delivery_date=None)
    quote_item = SimpleNamespace(rfq_item_id=1, quoted_quantity=Decimal("1"), unit_price=Decimal("100"),
        tax_rate=Decimal("13"), tax_included=None, supplier_product_id=None, supplier_model=None,
        unit_id=1, payment_terms=None, id=3)
    quote = SimpleNamespace(id=5, supplier_id=6, currency_code="CNY", rfq=SimpleNamespace(source_request_id=7))
    monkeypatch.setattr(service, "_validate_source", lambda *args: (SimpleNamespace(id=4), quote,
        SimpleNamespace(department_id=8), {1: rfq_item}, {1: quote_item}))
    with pytest.raises(BusinessValidationError, match="税务口径"):
        service.create_order(OrderSession(), SimpleNamespace(id=1), PurchaseOrderCreate(comparison_id=4, quote_id=5), commit=False)


@pytest.mark.parametrize(("included", "price", "expected_excl", "expected_tax"), [
    (True, "113", "100", "13"), (False, "100", "100", "13"),
    (None, "100", "100", "13"),
])
def test_reconciliation_respects_order_tax_basis(monkeypatch, included, price, expected_excl, expected_tax):
    line = {"id": 1, "line_no": 1, "product_id": 2, "product_name": "样品", "unit_id": 3,
            "unit_name": "件", "ordered_quantity": "1", "recorded_received_quantity": "1",
            "unit_price": price, "tax_rate": "13"}
    if included is not None:
        line["tax_included"] = included
    basis = {"order": {}, "lines": [line], "deliveries": [], "returns": [],
             "receipts": [{"id": 4, "po_item_id": 1, "product_id": 2, "unit_id": 3,
                           "status": "ACCEPTED", "quantity": "1"}]}
    monkeypatch.setattr(reconciliation_items, "collect_basis", lambda *args, **kwargs: basis)
    rows = []
    db = SimpleNamespace(add=rows.append, flush=lambda: None)
    rec = SimpleNamespace(id=9, items_version=0)
    reconciliation_items.append_basis(db, SimpleNamespace(id=1), rec, object(), ReconciliationItemsRefresh())
    assert rows[0].amount_excl_tax == Decimal(expected_excl)
    assert rows[0].tax_amount == Decimal(expected_tax)
    assert rows[0].amount_incl_tax == Decimal("113")


@pytest.mark.parametrize(("included", "price"), [(True, "113"), (False, "100"), (None, "100")])
def test_inbound_cost_uses_order_tax_basis(included, price):
    line = SimpleNamespace(unit_price=Decimal(price), tax_rate=Decimal("13"), tax_included=included)
    assert inventory_service.inbound_unit_cost(line) == Decimal("113")
