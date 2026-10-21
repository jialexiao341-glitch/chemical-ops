"""独立 MySQL 会话同时定标和下单；仅提交并清理本用例新建的来源链。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import delete, select, func

from app.core.db import SessionLocal
from app.core.errors import DuplicateResourceError
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
