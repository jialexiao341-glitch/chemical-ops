"""独立临时 MySQL 库中的正式下单并发回归（显式启用）。"""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessValidationError
from app.modules.purchase_orders import service
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequestItem


@pytest.mark.skipif(os.environ.get('CHEMICALOPS_ISOLATED_MYSQL_TEST') != '1', reason='需要显式启用独立 MySQL 验收')
def test_mysql_concurrent_orders_do_not_exceed_request(monkeypatch):
    settings = get_settings()
    root_password = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('MYSQL_ROOT_PASSWORD')
    if not root_password:
        pytest.skip('未配置隔离测试所需的 MySQL 管理凭据')
    source = settings.mysql_database
    assert source and source.replace('_', '').isalnum() and source.isascii()
    target = 'chemicalops_test_po_' + uuid4().hex[:16]
    assert target != source and target.startswith('chemicalops_test_po_')
    url = URL.create('mysql+pymysql', username='root', password=root_password,
                     host=settings.mysql_host, port=settings.mysql_port, query={'charset': 'utf8mb4'})
    admin = create_engine(url)
    created = False
    engine = None
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            created = True
            for table in ('purchase_request_items', 'rfq_items', 'supplier_quote_items', 'purchase_orders',
                          'purchase_order_items', 'purchase_order_approvals', 'purchase_order_events'):
                conn.exec_driver_sql(f'CREATE TABLE `{target}`.`{table}` LIKE `{source}`.`{table}`')
        engine = create_engine(url.set(database=target), isolation_level='REPEATABLE READ')
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO purchase_request_items (id, request_id, line_no, requested_name, quantity, unit_id) VALUES (21,31,1,'test',10,1)")
            conn.exec_driver_sql("INSERT INTO rfq_items (id, rfq_id, line_no, source_request_item_id, requested_name, quantity, unit_id) VALUES (11,1,1,21,'test',10,1)")
            conn.exec_driver_sql("INSERT INTO supplier_quote_items (id, quote_id, rfq_item_id, quoted_quantity, unit_id, unit_price) VALUES (41,1,11,10,1,1)")
            conn.exec_driver_sql("INSERT INTO purchase_orders (id, po_no, supplier_id, buyer_id, source_request_id, status) VALUES (1,'test-1',1,7,31,'APPROVED'),(2,'test-2',1,7,31,'APPROVED')")
            conn.exec_driver_sql("INSERT INTO purchase_order_items (po_id,line_no,product_id,source_quote_item_id,product_name_snapshot,order_quantity,unit_id,unit_price) VALUES (1,1,1,41,'test',10,1,1),(2,1,1,41,'test',10,1,1)")
        monkeypatch.setattr(service, '_assert_order_scope', lambda *args: None)
        monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
        barrier = Barrier(2)

        def place(identifier):
            with Session(engine, autoflush=False, expire_on_commit=False) as db:
                db.scalar(select(PurchaseRequestItem.quantity).where(PurchaseRequestItem.id == 21))
                barrier.wait(timeout=10)
                try:
                    service.place_order(db, SimpleNamespace(id=7), identifier)
                    return 'ordered'
                except BusinessValidationError:
                    db.rollback()
                    return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(place, [1, 2]))
        assert sorted(result) == ['ordered', 'rejected']
        with Session(engine) as db:
            assert db.get(PurchaseRequestItem, 21).fulfilled_quantity == Decimal('10')
            assert sorted(db.scalars(select(PurchaseOrder.status).order_by(PurchaseOrder.id))) == ['APPROVED', 'ORDERED']
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{target}`')
        admin.dispose()
