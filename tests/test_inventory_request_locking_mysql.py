"""独立 MySQL 库验证申请提交与取消并发状态流转。"""

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
from app.modules.inventory import crud, service
from app.modules.inventory.model import InventoryIssueRequest, InventoryTransferRequest, InventoryStocktakeRequest
from app.modules.inventory.schema import InventoryIssueRequestUpdate
from app.modules.replenishments import service as replenishments
from app.modules.replenishments.model import ReplenishmentRequest


@pytest.mark.skipif(os.environ.get('CHEMICALOPS_ISOLATED_MYSQL_TEST') != '1', reason='需要显式启用独立 MySQL 验收')
def test_mysql_submit_and_cancel_cannot_both_succeed(monkeypatch):
    settings = get_settings()
    password = dotenv_values(Path(__file__).resolve().parents[1] / '.env').get('MYSQL_ROOT_PASSWORD')
    if not password:
        pytest.skip('未配置隔离测试所需的 MySQL 管理凭据')
    source = settings.mysql_database
    assert source and source.replace('_', '').isalnum() and source.isascii()
    target = 'chemicalops_test_inv_' + uuid4().hex[:16]
    assert target != source and target.startswith('chemicalops_test_inv_')
    url = URL.create('mysql+pymysql', username='root', password=password,
        host=settings.mysql_host, port=settings.mysql_port, query={'charset': 'utf8mb4'})
    admin = create_engine(url)
    engine = None
    created = False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE `{target}` CHARACTER SET utf8mb4')
            created = True
            for table in ('inventory_issue_requests', 'inventory_issue_items', 'inventory_transfer_requests',
                          'inventory_transfer_items', 'inventory_stocktake_requests', 'inventory_stocktake_items',
                          'replenishment_requests', 'replenishment_items'):
                conn.exec_driver_sql(f'CREATE TABLE `{target}`.`{table}` LIKE `{source}`.`{table}`')
        engine = create_engine(url.set(database=target), isolation_level='REPEATABLE READ')
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO inventory_issue_requests (id,issue_no,applicant_id,purpose,status) VALUES (1,'test-issue',7,'test','DRAFT')")
            conn.exec_driver_sql("INSERT INTO inventory_issue_items (issue_request_id,line_no,product_id,warehouse_id,location_id,batch_id,unit_id,requested_quantity) VALUES (1,1,1,1,1,1,1,1)")
            conn.exec_driver_sql("INSERT INTO inventory_transfer_requests (id,transfer_no,applicant_id,purpose,status) VALUES (1,'test-transfer',7,'test','DRAFT')")
            conn.exec_driver_sql("INSERT INTO inventory_transfer_items (transfer_request_id,line_no,product_id,source_warehouse_id,source_location_id,target_warehouse_id,target_location_id,batch_id,unit_id,requested_quantity) VALUES (1,1,1,1,1,2,2,1,1,1)")
            conn.exec_driver_sql("INSERT INTO inventory_stocktake_requests (id,stocktake_no,applicant_id,warehouse_id,purpose,status) VALUES (1,'test-stocktake',7,1,'test','DRAFT')")
            conn.exec_driver_sql("INSERT INTO inventory_stocktake_items (stocktake_request_id,line_no,product_id,location_id,batch_id,unit_id,book_quantity,counted_quantity) VALUES (1,1,1,1,1,1,1,1)")
            conn.exec_driver_sql("INSERT INTO replenishment_requests (id,replenishment_no,supplier_id,applicant_id,reason,status) VALUES (1,'test-replenish',1,7,'test','DRAFT')")
        monkeypatch.setattr(service, 'get_user_role_codes', lambda *args: ['SYS_ADMIN'])
        monkeypatch.setattr(service, 'add_audit_log', lambda *args, **kwargs: None)
        monkeypatch.setattr(replenishments, '_can_manage_all', lambda *args: True)
        monkeypatch.setattr(replenishments, '_department_scope', lambda *args: True)
        monkeypatch.setattr(replenishments, 'get_user_role_codes', lambda *args: ['SYS_ADMIN'])
        monkeypatch.setattr(replenishments, '_enrich_header', lambda *args: None)
        monkeypatch.setattr(replenishments, '_enrich_items', lambda *args: None)
        cases = [
            (InventoryIssueRequest, service.submit_issue_request, service.cancel_issue_request),
            (InventoryTransferRequest, service.submit_transfer_request, service.cancel_transfer_request),
            (InventoryStocktakeRequest, service.submit_stocktake_request, service.cancel_stocktake_request),
            (ReplenishmentRequest, replenishments.submit_replenishment, replenishments.cancel_replenishment),
        ]
        for model, submit, cancel in cases:
            barrier = Barrier(2)
            def run(action):
                with Session(engine, autoflush=False, expire_on_commit=False) as db:
                    assert db.get(model, 1).status == 'DRAFT'
                    barrier.wait(timeout=10)
                    try:
                        action(db, SimpleNamespace(id=7), 1)
                        return 'success'
                    except BusinessValidationError:
                        db.rollback()
                        return 'rejected'
            with ThreadPoolExecutor(max_workers=2) as pool:
                result = list(pool.map(run, [submit, cancel]))
            assert sorted(result) == ['rejected', 'success']
            with Session(engine) as db:
                assert db.scalar(select(model.status).where(model.id == 1)) in {'SUBMITTED', 'CANCELLED'}

        # 编辑请求先取得旧快照，提交占住主单锁后应拒绝迟到编辑。
        with engine.begin() as conn:
            conn.exec_driver_sql("UPDATE inventory_issue_requests SET status='DRAFT', purpose='original' WHERE id=1")
        barrier = Barrier(2)
        def late_edit():
            with Session(engine, autoflush=False, expire_on_commit=False) as db:
                assert db.get(InventoryIssueRequest, 1).status == 'DRAFT'
                barrier.wait(timeout=10)
                try:
                    service.update_issue_request(db, SimpleNamespace(id=7), 1,
                        InventoryIssueRequestUpdate(purpose='late edit'))
                except BusinessValidationError:
                    db.rollback()
                    return 'rejected'
                return 'updated'
        with Session(engine, autoflush=False, expire_on_commit=False) as db, ThreadPoolExecutor(max_workers=1) as pool:
            db.scalar(select(InventoryIssueRequest).where(InventoryIssueRequest.id == 1).with_for_update())
            future = pool.submit(late_edit)
            barrier.wait(timeout=10)
            service.submit_issue_request(db, SimpleNamespace(id=7), 1)
            assert future.result(timeout=10) == 'rejected'
        with Session(engine) as db:
            row = db.get(InventoryIssueRequest, 1)
            assert row.status == 'SUBMITTED' and row.purpose == 'original'
        # 在已有一致性快照中，锁定读取仍须看到另一事务提交的最新明细。
        with Session(engine, autoflush=False, expire_on_commit=False) as reader:
            original = crud.get_issue_request(reader, 1)
            assert original.items[0].requested_quantity == 1
            with engine.begin() as conn:
                conn.exec_driver_sql('SELECT id FROM inventory_issue_requests WHERE id=1 FOR UPDATE')
                conn.exec_driver_sql('UPDATE inventory_issue_items SET requested_quantity=2 WHERE issue_request_id=1')
            current = crud.get_issue_request(reader, 1, for_update=True)
            assert current.items[0].requested_quantity == 2
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'DROP DATABASE `{target}`')
        admin.dispose()
