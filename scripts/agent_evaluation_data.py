"""agent-read-v1 固定隔离样本；复用工具层测试业务数据，RBAC 通过真实表查询。

日期采用中国标准时间当天的相对日期；不连接或修改开发业务库。
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@contextmanager
def evaluation_db():
    """每条任务重新生成样本、任务表与采购/仓储/财务权限记录。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE md_chemicals (id INTEGER PRIMARY KEY, chemical_name TEXT, english_name TEXT, alias_text TEXT, cas_no TEXT, status TEXT)",
            "CREATE TABLE md_products (id INTEGER PRIMARY KEY, product_name TEXT, status TEXT, product_code TEXT, model TEXT, packaging_spec TEXT, unit_id INTEGER, chemical_id INTEGER)",
            "CREATE TABLE md_units (id INTEGER PRIMARY KEY, unit_name TEXT, status TEXT)",
            "CREATE TABLE warehouses (id INTEGER PRIMARY KEY, warehouse_name TEXT, manager_id INTEGER, status TEXT, warehouse_code TEXT, region TEXT, address TEXT, note TEXT, created_at DATETIME, updated_at DATETIME)",
            "CREATE TABLE inventory_batches (id INTEGER PRIMARY KEY, batch_no TEXT, expiry_date DATE)",
            "CREATE TABLE inventory_balances (id INTEGER PRIMARY KEY, warehouse_id INTEGER, batch_id INTEGER, product_id INTEGER, unit_id INTEGER, status TEXT, quantity NUMERIC, locked_quantity NUMERIC)",
            "CREATE TABLE rfqs (id INTEGER PRIMARY KEY, rfq_no TEXT, requester_id INTEGER, status TEXT, source_request_id INTEGER)",
            "CREATE TABLE sys_users (id INTEGER PRIMARY KEY, department_id INTEGER)",
            "CREATE TABLE purchase_requests (id INTEGER PRIMARY KEY, department_id INTEGER)",
            "CREATE TABLE sys_user_department_scopes (user_id INTEGER PRIMARY KEY)",
            "CREATE TABLE sys_user_department_grants (user_id INTEGER, department_id INTEGER)",
            "CREATE TABLE sys_user_warehouse_scopes (user_id INTEGER PRIMARY KEY)",
            "CREATE TABLE sys_user_warehouse_grants (user_id INTEGER, warehouse_id INTEGER)",
            "CREATE TABLE rfq_items (id INTEGER PRIMARY KEY, rfq_id INTEGER, product_id INTEGER, specification TEXT, technical_requirements TEXT, unit_id INTEGER, quantity NUMERIC)",
            "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, supplier_name TEXT, status TEXT)",
            "CREATE TABLE supplier_quotes (id INTEGER PRIMARY KEY, rfq_id INTEGER, supplier_id INTEGER, quote_no TEXT, quote_version INTEGER, quote_date DATE, valid_until DATE, currency_code TEXT, status TEXT)",
            "CREATE TABLE supplier_quote_items (id INTEGER PRIMARY KEY, quote_id INTEGER, rfq_item_id INTEGER, unit_id INTEGER, supplier_model TEXT, tax_rate NUMERIC, tax_included INTEGER, unit_price NUMERIC, quoted_quantity NUMERIC, moq_quantity NUMERIC, moq_unit_id INTEGER, lead_days INTEGER, freight_amount NUMERIC, freight_tax_rate NUMERIC, freight_tax_included INTEGER, payment_terms TEXT)",
        ):
            conn.exec_driver_sql(ddl)
        for sql in (
            "INSERT INTO md_chemicals VALUES (1, '乙醇', 'Ethanol', '酒精,乙醇俗名;Ethyl alcohol', '64-17-5', 'ACTIVE')",
            "INSERT INTO md_products VALUES (1, '测试乙醇', 'ACTIVE', 'P-ETH', '分析纯', '20kg', 1, 1), (2, '停用产品', 'INACTIVE', 'P-OFF', NULL, NULL, 1, 1)",
            "INSERT INTO md_units VALUES (1, '千克', 'ACTIVE'), (2, '升', 'ACTIVE'), (3, '停用单位', 'INACTIVE')",
            "INSERT INTO warehouses (id, warehouse_name, manager_id, status) VALUES (1, '本人仓库', 7, 'ACTIVE'), (2, '其他仓库', 8, 'ACTIVE'), (3, '公共仓库', NULL, 'ACTIVE'), (4, '停用仓库', NULL, 'INACTIVE')",
            "INSERT INTO sys_user_warehouse_scopes VALUES (7), (8), (10)",
            "INSERT INTO sys_user_warehouse_grants VALUES (7, 1), (7, 3), (8, 2), (8, 3), (10, 1), (10, 2), (10, 3)",
            "INSERT INTO inventory_batches VALUES (1, '批次A', '2020-01-01'), (2, '批次B', NULL)",
            "INSERT INTO inventory_balances VALUES (1, 1, 1, 1, 1, 'AVAILABLE', 100, 20), (2, 1, 2, 1, 1, 'FROZEN', 50, 0), (3, 2, 2, 1, 1, 'AVAILABLE', 999, 0), (4, 3, 2, 1, 2, 'AVAILABLE', 5, 0), (5, 4, 2, 1, 1, 'AVAILABLE', 888, 0)",
            "INSERT INTO rfqs (id, rfq_no, requester_id, status) VALUES (1, 'RFQ-OWN', 7, 'RESPONDING'), (2, 'RFQ-OTHER', 8, 'RESPONDING'), (3, 'RFQ-CLOSED', 7, 'CLOSED')",
            "INSERT INTO rfq_items VALUES (11, 1, 1, '分析纯', '原始条件', 1, 20), (21, 2, 1, '分析纯', NULL, 1, 20), (31, 3, 1, '分析纯', NULL, 1, 20)",
        ):
            conn.exec_driver_sql(sql)
        for sid in range(1, 14):
            conn.exec_driver_sql("INSERT INTO suppliers VALUES (?, ?, ?)",
                                 (sid, f"测试供应商{sid}", "INACTIVE" if sid == 11 else "ACTIVE"))
        future, past = today + timedelta(days=5), today - timedelta(days=1)
        # ID、供应商、版本、价格、币种、单位、型号、税率、有效期、状态、报价日期。
        samples = [
            (1, 1, 1, 5, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (2, 1, 2, 10, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (3, 2, 1, 8, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (4, 3, 1, 1, 'CNY', 1, 'A', 13, past, 'SUBMITTED', today),
            (5, 4, 1, 3, 'CNY', 1, 'A', 13, None, 'SUBMITTED', today),
            (6, 5, 1, 1, 'USD', 1, 'A', 13, future, 'SUBMITTED', today),
            (7, 6, 1, 1, 'CNY', 2, 'A', 13, future, 'SUBMITTED', today),
            (8, 7, 1, 1, 'CNY', 1, 'A', None, future, 'SUBMITTED', today),
            (9, 8, 1, 1, 'CNY', 1, 'B', 13, future, 'SUBMITTED', today),
            (10, 9, 1, 1, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (11, 9, 2, 2, 'CNY', 1, 'A', 13, future, 'WITHDRAWN', today),
            (12, 10, 1, 1, 'CNY', 1, 'A', 13, future, 'SUBMITTED', future),
            (13, 11, 1, 1, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (14, 12, 1, 1, 'CNY', 3, 'A', 13, future, 'SUBMITTED', today),
            (15, 12, 1, 1, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
            (16, 13, 1, 1, 'CNY', 1, 'A', 13, future, 'SUBMITTED', today),
        ]
        for qid, sid, version, price, currency, unit, model, tax, valid, status, quoted in samples:
            conn.exec_driver_sql("INSERT INTO supplier_quotes VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)",
                                 (qid, sid, f"Q-{qid}", version, quoted, valid, currency, status))
            conn.exec_driver_sql("INSERT INTO supplier_quote_items (id, quote_id, rfq_item_id, unit_id, supplier_model, tax_rate, tax_included, unit_price, quoted_quantity, moq_quantity, moq_unit_id, lead_days) VALUES (?, ?, 11, ?, ?, ?, ?, ?, 20, 5, 1, 3)",
                                 (qid, qid, unit, model, tax, None if qid == 16 else 0 if qid == 15 else 1, price))
    from app.modules.ai.model import AIAgentTask
    AIAgentTask.__table__.create(engine)
    with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE sys_roles (id INTEGER PRIMARY KEY, role_code TEXT, status TEXT)",
            "CREATE TABLE sys_permissions (id INTEGER PRIMARY KEY, permission_code TEXT)",
            "CREATE TABLE sys_user_roles (user_id INTEGER, role_id INTEGER)",
            "CREATE TABLE sys_role_permissions (role_id INTEGER, permission_id INTEGER)",
        ):
            conn.exec_driver_sql(ddl)
        conn.exec_driver_sql("INSERT INTO sys_roles VALUES (1, 'PROCUREMENT', 'ACTIVE'), (2, 'WAREHOUSE', 'ACTIVE'), (3, 'FINANCE', 'ACTIVE'), (4, 'SYS_ADMIN', 'ACTIVE'), (5, 'PROCUREMENT_MANAGER', 'ACTIVE')")
        conn.exec_driver_sql("INSERT INTO sys_permissions VALUES (1, 'master.products.read'), (2, 'warehouse.inventory.read'), (3, 'procurement.rfqs.read')")
        conn.exec_driver_sql("INSERT INTO sys_user_roles VALUES (7,1), (8,2), (20,3), (9,4), (10,5)")
        conn.exec_driver_sql("INSERT INTO sys_role_permissions VALUES (1,1), (1,2), (1,3), (2,1), (2,2), (5,1), (5,2), (5,3)")
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
