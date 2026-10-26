"""采购并发约束与采购、到货、库存查询的行锁回归。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import delete, select, func

from app.core.db import SessionLocal
from app.core.errors import DuplicateResourceError
from app.modules.deliveries import crud as delivery_crud
from app.modules.inventory import crud as inventory_crud
from app.modules.products.model import Product
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User
from app.modules.system.audit import AuditLog
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem
from app.modules.rfqs.model import RFQ, RFQItem, SupplierQuote, SupplierQuoteItem, QuoteComparison, QuoteComparisonItem
from app.modules.rfqs.schema import QuoteSelection
from app.modules.rfqs.service import select_quote
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.schema import PurchaseOrderCreate
from app.modules.purchase_orders.service import create_order


def test_source_guard_rejects_duplicate_new_order(db_session):
    """即使绕过业务服务直接写库，新订单也不能复用已有来源。"""
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    source = db_session.execute(text(
        "SELECT source_comparison_id, supplier_id, buyer_id FROM purchase_orders "
        "WHERE source_comparison_id IS NOT NULL ORDER BY id LIMIT 1"
    )).mappings().one()
    with pytest.raises(IntegrityError) as error, db_session.begin_nested():
        db_session.execute(text(
            "INSERT INTO purchase_orders (po_no, source_comparison_id, supplier_id, buyer_id) "
            "VALUES (:po_no, :source_comparison_id, :supplier_id, :buyer_id)"
        ), {**source, "po_no": f"GUARD-{uuid4().hex[:12]}"})
    assert error.value.orig.args[0] == 1062
    assert 'uk_purchase_order_comparison' in str(error.value.orig)


def test_legacy_source_exception_has_auditable_snapshot(db_session):
    """历史豁免逐单记录原始来源，且仍由一张普通订单占用唯一键。"""
    from sqlalchemy import text

    rows = db_session.execute(text(
        "SELECT p.id, p.source_comparison_id, a.source_comparison_id AS original_source "
        "FROM purchase_orders p JOIN purchase_order_source_exceptions a ON a.po_id=p.id "
        "WHERE p.legacy_source_duplicate=1"
    )).mappings().all()
    assert all(row['source_comparison_id'] == row['original_source'] for row in rows)
    for row in rows:
        assert db_session.scalar(text(
            "SELECT COUNT(*) FROM purchase_orders WHERE source_comparison_guard=:source"
        ), {"source": row['original_source']}) == 1


def test_source_exception_cannot_be_supplied_by_client():
    import pytest
    from pydantic import ValidationError
    from app.modules.purchase_orders.schema import PurchaseOrderUpdate

    for schema, payload in ((PurchaseOrderCreate, {"comparison_id": 1, "quote_id": 1}),
                            (PurchaseOrderUpdate, {})):
        with pytest.raises(ValidationError):
            schema(**payload, legacy_source_duplicate=True)


def test_source_guard_migration_replay_does_not_expand_exceptions(db_session):
    import importlib.util
    import sys
    from pathlib import Path
    from sqlalchemy import text

    path = Path(__file__).resolve().parents[1] / 'scripts/migrate_database.py'
    spec = importlib.util.spec_from_file_location('source_guard_migration_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    migration = next(m for m in module._migration_files() if m.version == '053')
    before = db_session.execute(text('SELECT * FROM purchase_order_source_exceptions ORDER BY po_id')).all()
    module._apply_purchase_order_source_guard(db_session.connection(), migration)
    assert db_session.execute(text('SELECT * FROM purchase_order_source_exceptions ORDER BY po_id')).all() == before


def test_mysql_concurrent_selection_and_order_creation(db_engine):
    suffix = uuid4().hex[:12]
    request_id = rfq_id = comparison_id = None
    quote_ids = []
    try:
        with SessionLocal() as db:
            actor = db.scalar(select(User).where(User.username == "system_admin"))
            product = db.scalar(select(Product).where(Product.status == "ACTIVE").limit(1))
            supplier = db.scalar(select(Supplier).where(Supplier.status == "ACTIVE").limit(1))
            assert actor and product and supplier
            actor_id = actor.id
            request = PurchaseRequest(request_no=f"RACE-PR-{suffix}", applicant_id=actor.id,
                                      department_id=actor.department_id, purpose="并发回归", status="APPROVED")
            request.items.append(PurchaseRequestItem(line_no=1, product_id=product.id, requested_name=product.product_name, quantity=2, unit_id=product.unit_id))
            db.add(request); db.flush()
            rfq = RFQ(rfq_no=f"RACE-RFQ-{suffix}", source_request_id=request.id, requester_id=actor.id, status="SENT")
            rfq.items.append(RFQItem(line_no=1, source_request_item_id=request.items[0].id, product_id=product.id, requested_name=product.product_name, quantity=2, unit_id=product.unit_id))
            db.add(rfq); db.flush()
            comparison = QuoteComparison(comparison_no=f"RACE-QC-{suffix}", rfq_id=rfq.id, created_by=actor.id, status="DRAFT")
            db.add(comparison); db.flush()
            for version in (1, 2):
                quote = SupplierQuote(quote_no=f"RACE-Q{version}-{suffix}", rfq_id=rfq.id, supplier_id=supplier.id, quote_version=version, status="SUBMITTED")
                quote.items.append(SupplierQuoteItem(rfq_item_id=rfq.items[0].id, quoted_quantity=2, unit_id=product.unit_id, unit_price=version))
                db.add(quote); db.flush()
                comparison.items.append(QuoteComparisonItem(quote_id=quote.id, rfq_item_id=rfq.items[0].id, supplier_id=supplier.id, quoted_unit_price=version))
                quote_ids.append(quote.id)
            request_id, rfq_id, comparison_id = request.id, rfq.id, comparison.id
            db.commit()

        barrier = Barrier(2)
        def select_candidate(quote_id):
            with SessionLocal() as db:
                actor = db.get(User, actor_id)
                barrier.wait(timeout=10)
                try:
                    select_quote(db, actor, rfq_id, QuoteSelection(comparison_id=comparison_id, quote_id=quote_id, selection_reason="并发回归"))
                    return quote_id
                except DuplicateResourceError:
                    db.rollback()
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            selections = list(pool.map(select_candidate, quote_ids))
        winners = [value for value in selections if value is not None]
        assert len(winners) == 1

        barrier = Barrier(2)
        def place_order(_):
            with SessionLocal() as db:
                actor = db.get(User, actor_id)
                barrier.wait(timeout=10)
                try:
                    return create_order(db, actor, PurchaseOrderCreate(comparison_id=comparison_id, quote_id=winners[0])).id
                except DuplicateResourceError:
                    db.rollback()
                    return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            orders = list(pool.map(place_order, range(2)))
        assert len([value for value in orders if value is not None]) == 1
        with SessionLocal() as db:
            assert db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.source_comparison_id == comparison_id)) == 1
    finally:
        if request_id is not None:
            with SessionLocal() as db:
                orders = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.source_comparison_id == comparison_id)).all())
                for order in orders:
                    db.execute(delete(AuditLog).where(AuditLog.resource_type == "PURCHASE_ORDER", AuditLog.resource_id == order.id))
                    db.delete(order)
                db.flush()
                db.execute(delete(AuditLog).where(AuditLog.resource_type == "RFQ", AuditLog.resource_id == rfq_id))
                # 显式依赖顺序，避免 selected_quote_id 引用阻碍清理。
                db.execute(delete(QuoteComparisonItem).where(QuoteComparisonItem.comparison_id == comparison_id))
                db.execute(delete(QuoteComparison).where(QuoteComparison.id == comparison_id))
                db.execute(delete(SupplierQuoteItem).where(SupplierQuoteItem.quote_id.in_(quote_ids)))
                db.execute(delete(SupplierQuote).where(SupplierQuote.id.in_(quote_ids)))
                db.execute(delete(RFQItem).where(RFQItem.rfq_id == rfq_id))
                db.execute(delete(RFQ).where(RFQ.id == rfq_id))
                db.execute(delete(PurchaseRequestItem).where(PurchaseRequestItem.request_id == request_id))
                db.execute(delete(PurchaseRequest).where(PurchaseRequest.id == request_id))
                db.commit()


def _captured_statement(callable_, *args, **kwargs):
    db = Mock()
    db.scalar.side_effect = lambda statement: statement
    return callable_(db, *args, **kwargs)

def test_delivery_query_can_lock_delivery_row():
    statement = _captured_statement(delivery_crud.get_by_id, 1, for_update=True)

    assert statement._for_update_arg is not None

def test_purchase_order_query_can_lock_order_row():
    statement = _captured_statement(delivery_crud.get_order, 1, for_update=True)

    assert statement._for_update_arg is not None

def test_inventory_balance_query_can_lock_balance_row():
    statement = _captured_statement(inventory_crud.get_balance, 1, 2, 3, 4, 5, for_update=True)

    assert statement._for_update_arg is not None
