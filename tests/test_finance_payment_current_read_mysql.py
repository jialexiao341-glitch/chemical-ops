"""在独立 MySQL 临时库验证付款申请占用额度的并发一致性。"""

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
from app.modules.finance import service
from app.modules.finance.model import FinancePayment, FinanceReconciliation
from app.modules.finance.schema import PaymentCreate


@pytest.mark.skipif(os.environ.get('CHEMICALOPS_ISOLATED_MYSQL_TEST') != '1', reason='需要显式启用独立 MySQL 验收')
def test_mysql_concurrent_payments_use_latest_occupancy(monkeypatch):
    settings = get_settings()
    root_password = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('MYSQL_ROOT_PASSWORD')
    if not root_password:
        pytest.skip('未配置隔离测试所需的 MySQL 管理凭据')
    source = settings.mysql_database
    assert source and source.replace('_', '').isalnum() and source.isascii()
    target = 'chemicalops_test_fin_' + uuid4().hex[:16]
    assert target != source and target.startswith('chemicalops_test_fin_')
    url = URL.create('mysql+pymysql', username='root', password=root_password,
                     host=settings.mysql_host, port=settings.mysql_port, query={'charset': 'utf8mb4'})
    admin = create_engine(url)
    created = False
    engine = None
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            created = True
            for table in ('finance_reconciliations', 'finance_invoices', 'finance_payments'):
                conn.exec_driver_sql(f'CREATE TABLE `{target}`.`{table}` LIKE `{source}`.`{table}`')
        engine = create_engine(url.set(database=target), isolation_level='REPEATABLE READ')
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO finance_reconciliations (id,reconciliation_no,po_id,supplier_id,total_amount,status,created_by) VALUES (1,'test-rec',1,1,100,'CONFIRMED',7)")
            conn.exec_driver_sql("INSERT INTO finance_invoices (invoice_no,reconciliation_id,po_id,supplier_id,invoice_number,invoice_date,amount_excl_tax,tax_amount,amount_incl_tax,status,submitted_by) VALUES ('test-invoice',1,1,1,'test',CURRENT_DATE,100,0,100,'VERIFIED',7)")
        monkeypatch.setattr(service, '_require_finance_scope', lambda *args: None)
        monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
        barrier = Barrier(2)

        def create_payment(_):
            with Session(engine, autoflush=False, expire_on_commit=False) as db:
                db.scalar(select(FinancePayment.id).where(FinancePayment.reconciliation_id == 1))
                barrier.wait(timeout=10)
                try:
                    service.create_payment(db, SimpleNamespace(id=7), PaymentCreate(
                        reconciliation_id=1, amount=Decimal('60'), payment_method='BANK_TRANSFER'))
                    return 'created'
                except BusinessValidationError:
                    db.rollback()
                    return 'rejected'

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(create_payment, [1, 2]))
        assert sorted(result) == ['created', 'rejected']
        with Session(engine) as db:
            rows = list(db.scalars(select(FinancePayment)))
            assert len(rows) == 1 and rows[0].amount == Decimal('60')
            assert db.get(FinanceReconciliation, 1).total_amount == Decimal('100')
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{target}`')
        admin.dispose()
