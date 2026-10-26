"""订单来源校验复用真实报价读取入口，并按需生成 MySQL 行锁查询。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.modules.purchase_orders import crud, service
from app.modules.purchase_orders.schema import PurchaseOrderCreate


class ReadSession:
    def __init__(self, values):
        self.values = iter(values)
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)
        return next(self.values)


@pytest.mark.parametrize("for_update", [False, True])
def test_quote_loader_supports_optional_mysql_row_lock(for_update):
    quote = object()
    db = ReadSession([quote])
    assert crud.get_quote(db, 81, for_update=for_update) is quote
    statement = db.statements[0]
    compiled = statement.compile(dialect=mysql.dialect())
    assert ("FOR UPDATE" in str(compiled)) is for_update
    assert 81 in compiled.params.values()
    if for_update:
        assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("for_update", [False, True])
def test_order_source_validation_uses_real_quote_loader(monkeypatch, for_update):
    rfq_item = SimpleNamespace(id=71, line_no=1, product_id=9, source_request_item_id=61)
    rfq = SimpleNamespace(source_request_id=51, items=[rfq_item])
    comparison = SimpleNamespace(status="CONFIRMED", selected_quote_id=81)
    quote_item = SimpleNamespace(rfq_item_id=71, quoted_quantity=Decimal("2"))
    quote = SimpleNamespace(status="SELECTED", rfq=rfq, items=[quote_item])
    request = SimpleNamespace(status="APPROVED", items=[SimpleNamespace(
        id=61, quantity=Decimal("3"), fulfilled_quantity=Decimal("0"))])
    db = ReadSession([41, rfq, comparison, quote])
    scope_calls = []

    def scoped_request(_db, _user, request_id, *, for_update=False):
        scope_calls.append((request_id, for_update))
        return request

    monkeypatch.setattr(service, "get_scoped_purchase_request", scoped_request)
    result = service._validate_source(db, SimpleNamespace(id=1),
        PurchaseOrderCreate(comparison_id=31, quote_id=81), for_update=for_update)
    assert result[:3] == (comparison, quote, request)
    assert scope_calls == [(51, for_update)]
    quote_query = db.statements[-1].compile(dialect=mysql.dialect())
    assert "supplier_quotes" in str(quote_query)
    assert ("FOR UPDATE" in str(quote_query)) is for_update


def test_quote_loader_default_remains_read_only():
    db = ReadSession([None])
    assert crud.get_quote(db, 81) is None
    assert "FOR UPDATE" not in str(db.statements[0].compile(dialect=mysql.dialect()))
