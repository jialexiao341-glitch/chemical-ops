"""采购订单草稿领域服务和迁移契约。"""

from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.modules.purchase_orders import service as order_service
from app.modules.purchase_orders.schema import PurchaseOrderCreate, PurchaseOrderItemRead


ROOT = Path(__file__).resolve().parents[1]


class _OrderSession:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.flushes = 0

    def scalar(self, _query):
        return None

    def add(self, value):
        self.added.append(value)

    def begin_nested(self):
        return nullcontext()

    def flush(self):
        self.flushes += 1
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = 42

    def commit(self):
        self.commits += 1


@pytest.fixture
def source(monkeypatch):
    product_a = SimpleNamespace(id=11, line_no=1, requested_name="甲", product_id=21, required_delivery_date=None)
    product_b = SimpleNamespace(id=12, line_no=2, requested_name="乙", product_id=22, required_delivery_date=None)
    quote_item_a = SimpleNamespace(
        id=101, rfq_item_id=11, supplier_product_id=None, supplier_model="A", quoted_quantity=2,
        unit_id=3, unit_price=10, tax_rate=13, payment_terms="先款后货",
    )
    quote_item_b = SimpleNamespace(
        id=102, rfq_item_id=12, supplier_product_id=None, supplier_model="B", quoted_quantity=4,
        unit_id=3, unit_price=20, tax_rate=13, payment_terms=None,
    )
    comparison = SimpleNamespace(id=7)
    request = SimpleNamespace(id=9, department_id=2)
    quote = SimpleNamespace(
        id=8, supplier_id=5, currency_code="CNY",
        rfq=SimpleNamespace(source_request_id=9),
    )
    monkeypatch.setattr(
        order_service, "_validate_source",
        lambda *_args: (comparison, quote, request, {11: product_a, 12: product_b},
                        {11: quote_item_a, 12: quote_item_b}),
    )
    monkeypatch.setattr(order_service, "add_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(order_service, "_add_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(order_service, "_require_order", lambda _db, _order_id: _db.added[0])
    return SimpleNamespace(comparison=comparison, quote=quote)


def test_order_lines_copy_each_quote_line_payment_terms(source):
    db = _OrderSession()

    order = order_service.create_order(
        db, SimpleNamespace(id=3), PurchaseOrderCreate(comparison_id=7, quote_id=8), commit=False
    )

    assert [item.payment_terms_snapshot for item in order.items] == ["先款后货", None]
    assert [item.source_quote_item_id for item in order.items] == [101, 102]
    assert order.status == "DRAFT"


def test_commit_false_flushes_for_number_without_committing(source):
    db = _OrderSession()

    order = order_service.create_order(
        db, SimpleNamespace(id=3), PurchaseOrderCreate(comparison_id=7, quote_id=8), commit=False
    )

    assert order.id == 42
    assert order.po_no.endswith("000042")
    assert db.flushes >= 1
    assert db.commits == 0


def test_default_create_order_keeps_owning_commit_behavior(source):
    db = _OrderSession()

    order_service.create_order(db, SimpleNamespace(id=3), PurchaseOrderCreate(comparison_id=7, quote_id=8))

    assert db.commits == 1


def test_payment_terms_snapshot_is_exposed_by_order_item_schema():
    assert "payment_terms_snapshot" in PurchaseOrderItemRead.model_fields


def test_migration_058_is_discovered_and_only_adds_nullable_snapshot_column():
    from scripts.migrate_database import _migration_files

    migration = next(item for item in _migration_files() if item.version == "058")
    sql = migration.path.read_text(encoding="utf-8").upper()

    assert "ALTER TABLE PURCHASE_ORDER_ITEMS" in sql
    assert "ADD COLUMN PAYMENT_TERMS_SNAPSHOT VARCHAR(255) NULL" in " ".join(sql.split())
    assert "UPDATE PURCHASE_ORDER_ITEMS" not in sql
    assert "DROP COLUMN" not in sql
