"""在独立 MySQL 临时库验证定标与迟到报价的锁定顺序。"""

import os
from concurrent.futures import ThreadPoolExecutor
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
from app.modules.rfqs import crud, service
from app.modules.rfqs.model import RFQ, SupplierQuote
from app.modules.rfqs.schema import QuoteSelection


@pytest.mark.skipif(os.environ.get('CHEMICALOPS_ISOLATED_MYSQL_TEST') != '1', reason='需要显式启用独立 MySQL 验收')
def test_mysql_quote_cannot_reopen_selected_rfq(monkeypatch):
    settings = get_settings()
    root_password = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('MYSQL_ROOT_PASSWORD')
    if not root_password:
        pytest.skip('未配置隔离测试所需的 MySQL 管理凭据')
    source = settings.mysql_database
    assert source and source.replace('_', '').isalnum() and source.isascii()
    target = 'chemicalops_test_rfq_' + uuid4().hex[:16]
    assert target != source and target.startswith('chemicalops_test_rfq_')
    url = URL.create('mysql+pymysql', username='root', password=root_password,
                     host=settings.mysql_host, port=settings.mysql_port, query={'charset': 'utf8mb4'})
    admin = create_engine(url)
    created = False
    engine = None
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            created = True
            for table in ('rfqs', 'rfq_items', 'rfq_suppliers', 'supplier_quotes', 'supplier_quote_items',
                          'quote_comparisons', 'quote_comparison_items'):
                conn.exec_driver_sql(f'CREATE TABLE `{target}`.`{table}` LIKE `{source}`.`{table}`')
        engine = create_engine(url.set(database=target), isolation_level='REPEATABLE READ')
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO rfqs (id,rfq_no,requester_id,status) VALUES (1,'test-rfq',7,'RESPONDING')")
            conn.exec_driver_sql("INSERT INTO rfq_items (id,rfq_id,line_no,requested_name,quantity,unit_id) VALUES (11,1,1,'test',10,1)")
            conn.exec_driver_sql("INSERT INTO rfq_suppliers (rfq_id,supplier_id) VALUES (1,5)")
            conn.exec_driver_sql("INSERT INTO supplier_quotes (id,quote_no,rfq_id,supplier_id,quote_version,status) VALUES (21,'test-quote',1,5,1,'SUBMITTED')")
            conn.exec_driver_sql("INSERT INTO supplier_quote_items (id,quote_id,rfq_item_id,quoted_quantity,unit_id,unit_price) VALUES (41,21,11,10,1,1)")
            conn.exec_driver_sql("INSERT INTO quote_comparisons (id,comparison_no,rfq_id,created_by,status) VALUES (31,'test-comparison',1,7,'DRAFT')")
            conn.exec_driver_sql("INSERT INTO quote_comparison_items (comparison_id,quote_id,rfq_item_id,supplier_id) VALUES (31,21,11,5)")
        monkeypatch.setattr(service, 'get_rfq', lambda db, user, rfq_id, **kwargs: crud.get_by_id(db, rfq_id))
        monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
        barrier = Barrier(2)

        def late_quote():
            with Session(engine, autoflush=False, expire_on_commit=False) as db:
                stale = db.get(RFQ, 1)
                assert stale.status == 'RESPONDING'
                barrier.wait(timeout=10)
                try:
                    service.create_quote_for_supplier(db, SimpleNamespace(id=7), stale, 5, object())
                except BusinessValidationError:
                    db.rollback()
                    return 'rejected'
                return 'accepted'

        with Session(engine, autoflush=False, expire_on_commit=False) as selector, ThreadPoolExecutor(max_workers=1) as pool:
            selector.scalar(select(RFQ).where(RFQ.id == 1).with_for_update())
            future = pool.submit(late_quote)
            barrier.wait(timeout=10)
            service.select_quote(selector, SimpleNamespace(id=7), 1,
                QuoteSelection(comparison_id=31, quote_id=21, selection_reason='test'))
            assert future.result(timeout=10) == 'rejected'
        with Session(engine) as db:
            assert db.get(RFQ, 1).status == 'CLOSED'
            assert list(db.scalars(select(SupplierQuote.status))) == ['SELECTED']
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{target}`')
        admin.dispose()
