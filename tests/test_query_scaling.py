"""分页正确性与列表查询数不随页大小增长。"""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.modules.inventory import service as inventory
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.inventory_cost import service as costs
from app.modules.supplier_portal import service as portal
from app.modules.supplier_portal.model import SupplierQualityDocument
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.deliveries.model import Delivery
from app.modules.system.file_model import SysFile
from app.modules.system.model import User
from tests.test_remediation_boundaries import stock_fixture


def test_issue_options_scope_and_second_page(db_session, monkeypatch):
    actor, slot = stock_fixture(db_session)
    key = uuid4().hex[:10]
    for number in range(3):
        batch = InventoryBatch(product_id=slot['product_id'], batch_no=f'{key}-{number}', expiry_date=date.today())
        db_session.add(batch); db_session.flush()
        db_session.add(InventoryBalance(**{**slot, 'batch_id': batch.id}, quantity=2, locked_quantity=0, status='AVAILABLE'))
    db_session.flush()
    monkeypatch.setattr(inventory, 'accessible_warehouse_ids', lambda *_: {slot['warehouse_id']})
    first = inventory.list_issue_request_options(db_session, actor, keyword=key, page=1, page_size=2)
    second = inventory.list_issue_request_options(db_session, actor, keyword=key, page=2, page_size=2)
    assert len(first) == 2 and len(second) == 1
    assert {r['id'] for r in first}.isdisjoint(r['id'] for r in second)
    monkeypatch.setattr(inventory, 'accessible_warehouse_ids', lambda *_: set())
    assert inventory.list_issue_request_options(db_session, actor, keyword=key) == []


def test_expiry_has_bounded_pages(db_session):
    actor, slot = stock_fixture(db_session)
    for number in range(3):
        batch = InventoryBatch(product_id=slot['product_id'], batch_no=f'EXP-{uuid4().hex[:10]}', expiry_date=date.today())
        db_session.add(batch); db_session.flush()
        db_session.add(InventoryBalance(**{**slot, 'batch_id': batch.id}, quantity=1, locked_quantity=0, status='AVAILABLE'))
    db_session.flush()
    first = costs.list_expiry_alerts(db_session, days=0, warehouse_ids={slot['warehouse_id']}, page=1, page_size=2)
    second = costs.list_expiry_alerts(db_session, days=0, warehouse_ids={slot['warehouse_id']}, page=2, page_size=2)
    assert len(first) == len(second) == 2
    assert {(r[0].id, r[1].id) for r in first}.isdisjoint((r[0].id, r[1].id) for r in second)
    assert costs.list_expiry_alerts(db_session, days=0, warehouse_ids=set(), page=1, page_size=2) == []


@pytest.mark.parametrize('kind', ['shipments', 'quality'])
def test_supplier_list_query_count_constant(db_session, monkeypatch, kind):
    order = db_session.scalar(select(PurchaseOrder).limit(1))
    actor = db_session.scalar(select(User).limit(1))
    prefix = uuid4().hex[:10]
    monkeypatch.setattr(portal, '_supplier_id', lambda *_: order.supplier_id)
    for number in range(3):
        if kind == 'shipments':
            row = Delivery(delivery_no=f'{prefix}-{number}', po_id=order.id, supplier_id=order.supplier_id)
        else:
            file = SysFile(file_name=f'{prefix}-{number}', object_key=uuid4().hex, mime_type='application/pdf',
                           file_size_bytes=1, sha256_hash='a'*64, file_category='QUALITY_REPORT', uploader_id=actor.id)
            db_session.add(file); db_session.flush()
            row = SupplierQualityDocument(document_no=f'{prefix}-{number}', po_id=order.id,
                supplier_id=order.supplier_id, file_id=file.id, document_type='COA', submitted_by=actor.id)
        db_session.add(row)
    db_session.flush()
    statements = []
    connection = db_session.connection()
    def capture(*args):
        statements.append(args[2])
    event.listen(connection, 'before_cursor_execute', capture)
    try:
        query = portal.list_shipment_notices if kind == 'shipments' else portal.list_quality_documents
        counts = []
        for page_size in (1, 20):
            statements.clear()
            result = query(db_session, actor, keyword=prefix, status=None, page=1, page_size=page_size)
            assert result.total == 3
            assert len(result.items) == min(page_size, 3)
            counts.append(len(statements))
        assert counts[0] == counts[1]
        assert counts[0] <= 3
    finally:
        event.remove(connection, 'before_cursor_execute', capture)
