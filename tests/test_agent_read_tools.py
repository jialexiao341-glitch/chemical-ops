"""只读工具的真实查询、权限、报价可比性和无写入回归；使用隔离 SQLite 样本。"""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai import agent_tools as tools
from app.modules.ai import capabilities
from app.modules.ai.controller import router
from app.modules.inventory import service as inventory_service


def allow_ai_workspace_permission(app):
    """Bypass only the database-backed RBAC guard in isolated router tests."""
    guard = router.dependencies[0].dependency
    app.dependency_overrides[guard] = lambda: None


@pytest.fixture
def tool_db(monkeypatch):
    """建立隔离业务样本和角色权限替身；查询执行真实 SQL，测试后销毁数据库。"""
    roles = {9: ["SYS_ADMIN"], 10: ["PROCUREMENT_MANAGER"]}
    permissions = {7: ["master.products.read", "master.suppliers.read", "warehouse.inventory.read", "procurement.rfqs.read", "procurement.requests.read", "procurement.orders.read", "warehouse.deliveries.read", "finance.reconciliations.read", "finance.invoices.read", "finance.payments.read"],
                   8: ["warehouse.inventory.read"], 10: ["master.products.read", "warehouse.inventory.read", "procurement.rfqs.read"]}
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(agent_enabled=True, agent_tool_timeout_seconds=15))
    monkeypatch.setattr(tools, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda _db, uid: permissions.get(uid, []))
    monkeypatch.setattr(inventory_service, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    # Agent runtime now builds a routing capability manifest from the same RBAC
    # fixture; keep it isolated from production system tables.
    monkeypatch.setattr(capabilities, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    monkeypatch.setattr(capabilities, "get_user_permission_codes", lambda _db, uid: permissions.get(uid, []))
    monkeypatch.setattr(capabilities, "agent_enabled", lambda: True)
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
            "CREATE TABLE rfqs (id INTEGER PRIMARY KEY, rfq_no TEXT, requester_id INTEGER, status TEXT)",
            "CREATE TABLE rfq_items (id INTEGER PRIMARY KEY, rfq_id INTEGER, product_id INTEGER, specification TEXT, technical_requirements TEXT, unit_id INTEGER, quantity NUMERIC)",
            "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, supplier_name TEXT, status TEXT)",
            "CREATE TABLE supplier_quotes (id INTEGER PRIMARY KEY, rfq_id INTEGER, supplier_id INTEGER, quote_no TEXT, quote_version INTEGER, quote_date DATE, valid_until DATE, currency_code TEXT, status TEXT)",
            "CREATE TABLE supplier_quote_items (id INTEGER PRIMARY KEY, quote_id INTEGER, rfq_item_id INTEGER, unit_id INTEGER, supplier_model TEXT, tax_rate NUMERIC, tax_included INTEGER, unit_price NUMERIC, quoted_quantity NUMERIC, moq_quantity NUMERIC, moq_unit_id INTEGER, lead_days INTEGER, freight_amount NUMERIC, freight_tax_rate NUMERIC, freight_tax_included INTEGER, payment_terms TEXT)",
        ):
            conn.exec_driver_sql(ddl)
        for sql in (
            "INSERT INTO md_chemicals VALUES (1, '乙醇', 'Ethanol', '酒精,乙醇俗名;Ethyl alcohol', '64-17-5', 'ACTIVE'), (2, '停用化学品', 'Inactive compound', '停用别名', '00-00-0', 'INACTIVE')",
            "INSERT INTO md_products (id, product_name, status, product_code, model, packaging_spec, unit_id, chemical_id) VALUES (1, '测试乙醇', 'ACTIVE', 'P-ETH', '分析纯', '20kg', 1, 1), (2, '停用产品', 'INACTIVE', 'P-OFF', NULL, NULL, 1, 2)",
            "INSERT INTO md_units VALUES (1, '千克', 'ACTIVE'), (2, '升', 'ACTIVE'), (3, '停用单位', 'INACTIVE')",
            "INSERT INTO warehouses (id, warehouse_code, warehouse_name, manager_id, status) VALUES (1, 'WH-OWN', '本人仓库', 7, 'ACTIVE'), (2, 'WH-OTHER', '其他仓库', 8, 'ACTIVE'), (3, 'WH-PUBLIC', '公共仓库', NULL, 'ACTIVE'), (4, 'WH-OFF', '停用仓库', NULL, 'INACTIVE')",
            "INSERT INTO inventory_batches VALUES (1, '批次A', '2020-01-01'), (2, '批次B', NULL)",
            "INSERT INTO inventory_balances VALUES (1, 1, 1, 1, 1, 'AVAILABLE', 100, 20), (2, 1, 2, 1, 1, 'FROZEN', 50, 0), (3, 2, 2, 1, 1, 'AVAILABLE', 999, 0), (4, 3, 2, 1, 2, 'AVAILABLE', 5, 0), (5, 4, 2, 1, 1, 'AVAILABLE', 888, 0)",
            "INSERT INTO rfqs VALUES (1, 'RFQ-OWN', 7, 'RESPONDING'), (2, 'RFQ-OTHER', 8, 'RESPONDING'), (3, 'RFQ-CLOSED', 7, 'CLOSED')",
            "INSERT INTO rfq_items VALUES (11, 1, 1, '分析纯', '原始条件', 1, 10), (21, 2, 1, '分析纯', NULL, 1, 10), (31, 3, 1, '分析纯', NULL, 1, 10)",
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
            conn.exec_driver_sql("INSERT INTO supplier_quote_items VALUES (?, ?, 11, ?, ?, ?, ?, ?, 20, 5, 1, 3, ?, ?, ?, '月结30天')",
                                 (qid, qid, unit, model, tax, None if qid == 16 else 0 if qid == 15 else 1, price,
                                  20 if qid == 2 else None, 6 if qid == 2 else None, 0 if qid == 2 else None))
    with Session(engine) as session:
        yield session
    engine.dispose()


def call(db, name="inventory.query_available", actor_id=7, **arguments):
    """区分认证执行人与工具参数，使身份注入用例真正进入 Schema 校验。"""
    return tools.execute_tool(db, SimpleNamespace(id=actor_id), tools.ToolCall(tool=name, arguments=arguments))


def test_execute_tool_sets_and_resets_database_deadline(tool_db, monkeypatch):
    from app.modules.ai.tool_sql_timeout import current_tool_deadline

    spec = tools.TOOLS["catalog.search_products"]
    observed = []

    def record_deadline(db, user, arguments):
        observed.append(current_tool_deadline())
        return spec.handler(db, user, arguments)

    monkeypatch.setitem(tools.TOOLS, spec.name, replace(spec, handler=record_deadline))
    result = call(tool_db, name=spec.name, keyword="测试乙醇")

    assert result.total_rows == 1
    assert observed[0] is not None
    assert current_tool_deadline() is None


@pytest.mark.parametrize(("error_name", "result"), [
    ("timeout", "timeout"), ("unsupported", "unsupported"),
])
def test_tool_timeout_metric_has_only_low_cardinality_labels(tool_db, monkeypatch, error_name, result):
    from app.core.observability import metrics
    from app.modules.ai.tool_sql_timeout import ToolExecutionTimeout, ToolTimeoutUnsupported

    spec = tools.TOOLS["catalog.search_products"]
    observed = []
    original_increment = metrics.increment

    def record_metric(name, *, labels=None, value=1.0):
        if name == "agent_tool_sql_timeouts":
            observed.append((name, labels))
        return original_increment(name, labels=labels, value=value)

    def timed_out(*_args, **_kwargs):
        error = ToolExecutionTimeout if error_name == "timeout" else ToolTimeoutUnsupported
        raise error("database deadline elapsed")

    monkeypatch.setattr(metrics, "increment", record_metric)
    monkeypatch.setitem(tools.TOOLS, spec.name, replace(spec, handler=timed_out))
    error_type = ToolExecutionTimeout if error_name == "timeout" else ToolTimeoutUnsupported
    with pytest.raises(error_type):
        call(tool_db, name=spec.name, keyword="secret-user-query")

    assert observed == [("agent_tool_sql_timeouts", {
        "tool": spec.name, "dialect": "sqlite", "result": result,
    })]


def test_inventory_scope_totals_sources_and_frozen_balance(tool_db):
    """核验仓库隔离、冻结余额、分单位合计和返回明细来源。"""
    result = call(tool_db, product_id=1)
    assert result.total_rows == 3
    assert [row.balance_id for row in result.rows] == [1, 2, 4]
    assert {item.unit_id: item.available_quantity for item in result.totals} == {1: 80, 2: 5}
    assert result.rows[1].available_quantity == 0
    assert [source.record_id for source in result.sources] == [1, 2, 4]
    assert result.rows[0].expiry_date.year == 2020
    assert "有效期" not in result.scope  # 不把账面可用量包装成效期合格判定。
    assert "过期批次" in result.warnings[0]


def test_truncated_inventory_keeps_full_authorized_totals(tool_db):
    """分页上限只截断明细，不能截断全部授权余额的合计。"""
    result = call(tool_db, product_id=1, limit=1)
    assert result.truncated and len(result.rows) == 1
    assert {item.unit_id: item.available_quantity for item in result.totals} == {1: 80, 2: 5}


@pytest.mark.parametrize("uid", [9, 10])
def test_manager_scope_includes_other_active_warehouses(tool_db, uid):
    """管理角色可跨负责人查询，但不把停用仓库纳入当前工具。"""
    result = call(tool_db, actor_id=uid, product_id=1)
    assert result.total_rows == 4
    assert 3 in {row.balance_id for row in result.rows}
    assert 5 not in {row.balance_id for row in result.rows}


@pytest.mark.parametrize("warehouse_id", [2, 4, 999])
def test_inventory_unavailable_warehouse_not_disclosed(tool_db, warehouse_id):
    """不可访问、停用与不存在仓库统一处理，避免泄漏资源详情。"""
    with pytest.raises(ResourceNotFoundError, match="不可访问"):
        call(tool_db, product_id=1, warehouse_id=warehouse_id)


@pytest.mark.parametrize("product_id", [2, 999])
def test_product_must_exist_and_be_active(tool_db, product_id):
    """已停用或不存在的产品不进入采购工具查询。"""
    with pytest.raises(ResourceNotFoundError):
        call(tool_db, product_id=product_id)


def test_missing_permission_blocks_catalog_and_execution(tool_db):
    """同时核验工具目录过滤和绕过目录直接执行时的权限检查。"""
    user = SimpleNamespace(id=20)
    assert tools.list_tools(tool_db, user) == []
    with pytest.raises(AuthorizationError):
        call(tool_db, actor_id=20, product_id=1)
    assert [item['name'] for item in tools.list_tools(tool_db, SimpleNamespace(id=8))] == ['inventory.query_available']


def test_tool_catalog_exposes_explicit_governance_metadata(tool_db):
    catalog = tools.list_tools(tool_db, SimpleNamespace(id=9))

    assert len(catalog) == len(tools.TOOLS)
    for entry in catalog:
        assert entry["version"] == "1.0"
        assert entry["risk"] == "READ_ONLY"
        assert entry["retry_policy"] == "MANUAL_ONLY"
        assert entry["idempotent"] is True
        assert entry["cost_class"] == "DATABASE_READ"
        assert entry["quota_class"] == "UNMETERED"


@pytest.mark.parametrize("arguments", [
    {}, {"product_id": "1"}, {"product_id": True}, {"product_id": 0},
    {"product_id": 1, "limit": 101}, {"product_id": 1, "user_id": 9},
    {"product_id": 1, "sql": "SELECT * FROM sys_users"},
])
def test_invalid_or_identity_injected_arguments_rejected(tool_db, arguments):
    """拒绝缺项、错误类型、越界限额以及模型夹带的身份或 SQL。"""
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, **arguments)


def test_unknown_and_write_tools_rejected(tool_db):
    """任意函数名和草稿写工具都无法穿过静态只读注册表。"""
    for name in ['execute_sql', 'purchase_request.create_draft']:
        with pytest.raises(BusinessValidationError, match="未注册"):
            call(tool_db, name=name, product_id=1)


def test_quote_revision_expiry_currency_unit_tax_and_model_boundaries(tool_db, monkeypatch):
    """独立预期值核验报价有效性、版本选择及可比组排名。"""
    from app.modules.rfqs import service as rfq_service

    monkeypatch.setattr(rfq_service, "quality_history_by_supplier", lambda _db, _user, ids, **_kwargs: {
        supplier_id: {"status": "UNKNOWN", "reason": "当前账号无质量验收读取权限"}
        for supplier_id in ids
    })
    result = call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=11)
    assert result.total_rows == 9
    assert {row.quote_id: row.rank for row in result.rows} == {2: 2, 3: 1, 5: None, 6: None, 7: None, 8: None, 9: None, 15: None, 16: None}
    assert all(source.parent_id == 1 for source in result.sources)
    assert result.specification == "分析纯"
    assert result.model_dump(mode="json")["rows"][0]["unit_price"] == "10.000000"
    assert next(row for row in result.rows if row.quote_id == 15).tax_included is False
    assert next(row for row in result.rows if row.quote_id == 16).tax_included is None
    cost_row = next(row for row in result.rows if row.quote_id == 2)
    assert cost_row.cost_analysis["total_cost"] == "121.200000"
    assert cost_row.cost_analysis["complete"] is True
    assert result.recommendation["status"] == "RECOMMENDED"
    assert result.recommendation["candidate_quote_id"] == 2
    assert any("报价 3" in risk and "不完整" in risk for risk in result.recommendation["risks"])
    assert any("质量风险未知" in risk for risk in result.recommendation["risks"])
    assert any("含税口径" in warning for warning in result.warnings)


def test_truncated_quotes_are_never_ranked_as_complete_comparison(tool_db):
    """不把截断后的局部候选误标为完整比价排名。"""
    result = call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=11, limit=1)
    assert result.truncated and result.total_rows == 9
    assert all(row.rank is None for row in result.rows)


def test_quote_scope_does_not_disclose_other_user_item(tool_db):
    """同一明细在普通用户和采购经理的范围规则下产生不同可见性。"""
    with pytest.raises(ResourceNotFoundError):
        call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=21)
    result = call(tool_db, name="supplier_quotes.compare", actor_id=10, product_id=1, rfq_item_id=21)
    assert result.total_rows == 0 and result.sources == []


def test_closed_rfq_is_not_current_procurement_candidate(tool_db):
    """已关闭询价保留原业务历史入口，不能当作当前采购报价候选。"""
    with pytest.raises(BusinessValidationError, match="已关闭"):
        call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=31)


def test_agent_switch_disables_catalog_and_executor(tool_db, monkeypatch):
    """总开关关闭时，既不能读取工具目录，也不能执行工具。"""
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(agent_enabled=False))
    with pytest.raises(BusinessValidationError, match="关闭"):
        tools.list_tools(tool_db, SimpleNamespace(id=7))
    with pytest.raises(BusinessValidationError, match="关闭"):
        call(tool_db, product_id=1)


def test_tools_issue_only_reads_and_do_not_create_business_records(tool_db):
    """捕获实际执行语句，证明两个工具路径均未产生业务写入。"""
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        """记录 SQL 供只读断言使用，不修改执行语句。"""
        statements.append(statement)
    event.listen(tool_db.bind, "before_cursor_execute", capture)
    try:
        call(tool_db, product_id=1)
        call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=11)
    finally:
        event.remove(tool_db.bind, "before_cursor_execute", capture)
    assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def test_new_read_tools_use_exact_identifiers_and_registered_permissions(tool_db, monkeypatch):
    from app.modules.ai import order_trace
    from app.modules.purchase_requests import service as request_service

    request = SimpleNamespace(
        id=31, request_no="PR20261022000031", purpose="乙醇采购", priority="NORMAL",
        budget_amount=100, currency_code="CNY", expected_date=None, status="APPROVING",
        items=[SimpleNamespace(line_no=1, requested_name="乙醇", technical_requirements=None,
            quantity=2, unit_id=1, budget_price=50, expected_date=None, fulfilled_quantity=0, status="OPEN")],
        approvals=[SimpleNamespace(approver_id=999, opinion="敏感审批意见")],
    )
    seen = []
    def get_request_by_no(_db, _user, request_no):
        seen.append(request_no)
        return request if request_no == request.request_no else None
    monkeypatch.setattr(request_service, "get_request_by_no", get_request_by_no)
    result = call(tool_db, name="purchase_requests.get_by_no", request_no=request.request_no)
    assert result.total_rows == 1
    assert result.rows[0]["request_no"] == request.request_no
    assert "opinion" not in str(result.model_dump()) and "approver_id" not in str(result.model_dump())
    assert seen == [request.request_no]
    assert call(tool_db, name="purchase_requests.get_by_no", request_no="PR20261022000032").total_rows == 0

    expected = {
        "po_no": "PO-26001", "supplier": "供应商", "order_status": "OPEN",
        "order_updated_at": None, "stages": [], "conclusion": [],
        "unavailable_stages": ["发票"], "source_records": [], "answer": "追溯结果",
    }
    traced = []
    monkeypatch.setattr(order_trace, "trace_purchase_order", lambda _db, _user, po_no: traced.append(po_no) or expected)
    assert call(tool_db, name="purchase_orders.trace_by_no", po_no="PO-26001").answer == "追溯结果"
    assert traced == ["PO-26001"]


def test_new_read_tools_recheck_permissions_and_reject_extra_fields(tool_db):
    with pytest.raises(AuthorizationError):
        call(tool_db, actor_id=8, name="purchase_requests.get_by_no", request_no="PR20261022000031")
    with pytest.raises(AuthorizationError):
        call(tool_db, actor_id=8, name="purchase_orders.trace_by_no", po_no="PO-26001")
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="purchase_requests.get_by_no", request_no="PR20261022000031", user_id=7)


def test_quality_acceptance_tool_reads_only_exact_visible_acceptance(tool_db, monkeypatch):
    from app.modules.quality_acceptances import service as acceptance_service

    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: ["quality.acceptances.read"])
    acceptance = SimpleNamespace(
        id=44, acceptance_no="QA20261022000044", result="PENDING", inspection_time=None,
        test_result={"appearance": "符合"}, certificate_complete=1, report_file_id=12,
        conclusion="等待检验完成",
    )
    seen = []
    monkeypatch.setattr(acceptance_service, "get_acceptance_by_no",
        lambda _db, _user, number: seen.append(number) or (acceptance if number == acceptance.acceptance_no else None))

    result = call(tool_db, name="quality_acceptances.get_by_no", acceptance_no=acceptance.acceptance_no)

    assert result.total_rows == 1
    assert result.rows[0].acceptance_no == acceptance.acceptance_no
    assert result.rows[0].test_result == {"appearance": "符合"}
    assert result.rows[0].report_available is True
    assert result.sources[0].resource == "quality_acceptances"
    assert seen == [acceptance.acceptance_no]
    assert call(tool_db, name="quality_acceptances.get_by_no", acceptance_no="QA20261022000045").total_rows == 0


def test_quality_acceptance_tool_requires_permission_and_strict_number(tool_db, monkeypatch):
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: [])
    with pytest.raises(AuthorizationError):
        call(tool_db, name="quality_acceptances.get_by_no", acceptance_no="QA20261022000044")
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: ["quality.acceptances.read"])
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="quality_acceptances.get_by_no", acceptance_no="QA20261022000044", acceptance_id=44)
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="quality_acceptances.get_by_no", acceptance_no="QA?")


def test_delivery_tool_returns_exact_visible_receiving_facts(tool_db, monkeypatch):
    from app.modules.deliveries import service as delivery_service

    delivery = SimpleNamespace(
        id=51, delivery_no="DL20261022000051", status="RECEIVED",
        expected_arrival_date="2026-10-22", actual_arrival_date="2026-10-22",
        items=[SimpleNamespace(line_no=1, planned_quantity=10, actual_quantity=8,
                                short_quantity=2, document_complete=0)],
    )
    seen = []
    monkeypatch.setattr(delivery_service, "get_delivery_by_no",
        lambda _db, _user, number: seen.append(number) or (delivery if number == delivery.delivery_no else None))

    result = call(tool_db, name="deliveries.get_by_no", delivery_no=delivery.delivery_no)

    assert result.total_rows == 1
    assert result.rows[0].status == "RECEIVED"
    assert result.rows[0].items[0].short_quantity == 2
    assert result.rows[0].items[0].document_complete is False
    assert result.sources[0].resource == "deliveries"
    assert seen == [delivery.delivery_no]
    assert call(tool_db, name="deliveries.get_by_no", delivery_no="DL20261022000052").total_rows == 0


def test_delivery_tool_requires_permission_and_strict_number(tool_db, monkeypatch):
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: [])
    with pytest.raises(AuthorizationError):
        call(tool_db, name="deliveries.get_by_no", delivery_no="DL20261022000051")
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: ["warehouse.deliveries.read"])
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="deliveries.get_by_no", delivery_no="DL?")
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="deliveries.get_by_no", delivery_no="DL20261022000051", delivery_id=51)


def test_delivery_service_lookup_reuses_detail_scope_check(monkeypatch):
    from app.modules.deliveries import service as delivery_service

    user = SimpleNamespace(id=7)
    delivery = SimpleNamespace(id=51)
    scope_calls = []
    monkeypatch.setattr(delivery_service, "get_delivery",
        lambda _db, actor, delivery_id: scope_calls.append((actor, delivery_id)) or delivery)
    db = SimpleNamespace(scalar=lambda _query: 51)

    assert delivery_service.get_delivery_by_no(db, user, "DL20261022000051") is delivery
    assert scope_calls == [(user, 51)]


def test_finance_reconciliation_tool_returns_status_grouped_amounts(tool_db, monkeypatch):
    from app.modules.finance import service as finance_service
    from app.modules.ai import finance_read_model

    reconciliation = SimpleNamespace(id=71, reconciliation_no="FR20261022000071",
        status="CONFIRMED", currency_code="CNY", total_amount=100)
    monkeypatch.setattr(finance_service, "get_reconciliation_by_no",
        lambda _db, _user, number: reconciliation if number == reconciliation.reconciliation_no else None)
    monkeypatch.setattr(finance_read_model, "read_reconciliation", lambda *_args: {
        "version_no": 2, "source_changed": True, "line_warnings": ["来源已变化"],
        "lines": [{"reconciliation_item_id": 501, "line_no": 1, "product_name": "测试乙醇",
            "unit_name": "千克", "ordered_quantity": Decimal("10"), "received_quantity": Decimal("8"),
            "accepted_quantity": Decimal("8"), "returned_quantity": Decimal("0"),
            "reconciliation_quantity": Decimal("8"), "amount_incl_tax": Decimal("100"),
            "invoiced_reserved_amount": Decimal("80"), "verified_invoice_amount": Decimal("60"),
            "unmatched_invoice_capacity": Decimal("20"), "warnings": ["来源数量待核查"]}],
        "unallocated_invoices": ["FI20261022000001"],
        "invoices": [{"status": "VERIFIED", "count": 1, "amount": Decimal("80")}],
        "payments": [{"status": "PAID", "count": 1, "amount": Decimal("30")}],
        "payment_precheck": {"reconciliation_confirmed": True, "verified_invoice_amount": Decimal("60"),
            "active_payment_amount": Decimal("30"), "remaining_reconciliation_amount": Decimal("70"),
            "max_new_payment_amount": Decimal("60"), "currency_code": "CNY", "blockers": [],
            "limitation": "提交与审批仍会重新校验。"},
    })
    result = call(tool_db, name="finance_reconciliations.get_by_no",
        reconciliation_no=reconciliation.reconciliation_no)

    assert result.total_rows == 1
    assert result.rows[0].status == "CONFIRMED"
    assert result.rows[0].invoices[0].amount == 80
    assert result.rows[0].payments[0].amount == 30
    assert result.rows[0].lines[0].accepted_quantity == Decimal("8")
    assert result.rows[0].lines[0].verified_invoice_amount == Decimal("60")
    assert result.rows[0].source_changed is True
    assert result.rows[0].unallocated_invoices == ["FI20261022000001"]
    assert result.rows[0].payment_precheck.max_new_payment_amount == Decimal("60")
    assert result.sources[0].resource == "finance_reconciliations"


def test_finance_read_model_checks_permissions_and_caps_payment(tool_db, monkeypatch):
    from app.modules.ai import finance_read_model

    monkeypatch.setattr(finance_read_model, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(finance_read_model, "get_user_permission_codes", lambda *_args: [
        "finance.reconciliations.read", "finance.invoices.read", "finance.payments.read",
    ])
    monkeypatch.setattr(finance_read_model, "get_reconciliation", lambda _db, _user, _id:
        SimpleNamespace(id=71, status="CONFIRMED", total_amount=Decimal("100"), currency_code="CNY"))
    line = SimpleNamespace(id=501, line_no=1, product_name="乙醇", unit_name="千克",
        ordered_quantity=Decimal("10"), received_quantity=Decimal("8"), accepted_quantity=Decimal("8"),
        returned_quantity=Decimal("0"), reconciliation_quantity=Decimal("8"),
        amount_incl_tax=Decimal("100"), warnings=[])
    monkeypatch.setattr(finance_read_model.reconciliation_items, "read_items", lambda *_args:
        SimpleNamespace(version_no=3, source_changed=True, warnings=["来源已变化"], items=[line]))
    monkeypatch.setattr(finance_read_model.invoice_matches, "line_summary", lambda *_args: ([{
        "reconciliation_item_id": 501, "reserved_amount": "80", "verified_amount": "60",
        "remaining_amount": "20",
    }], ["FI-UNALLOCATED"]))

    class QueryRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    grouped = [
        [{"status": "VERIFIED", "count": 1, "amount": Decimal("80")}],
        [{"status": "REQUESTED", "count": 1, "amount": Decimal("40")}],
    ]
    monkeypatch.setattr(tool_db, "execute", lambda _query: QueryRows(grouped.pop(0)))
    result = finance_read_model.read_reconciliation(tool_db, SimpleNamespace(id=7), SimpleNamespace(id=71))

    assert result["source_changed"] is True
    assert result["unallocated_invoices"] == ["FI-UNALLOCATED"]
    assert result["payment_precheck"]["remaining_reconciliation_amount"] == Decimal("60")
    assert result["payment_precheck"]["max_new_payment_amount"] == Decimal("60")


def test_finance_read_model_handles_legacy_reconciliation_without_saved_lines(tool_db, monkeypatch):
    from app.modules.ai import finance_read_model

    monkeypatch.setattr(finance_read_model, "get_user_role_codes", lambda *_args: ["SYS_ADMIN"])
    monkeypatch.setattr(finance_read_model, "get_user_permission_codes", lambda *_args: [])
    monkeypatch.setattr(finance_read_model, "get_reconciliation", lambda _db, _user, _id:
        SimpleNamespace(id=72, status="DRAFT", total_amount=Decimal("100"), currency_code="CNY"))
    monkeypatch.setattr(finance_read_model.reconciliation_items, "read_items", lambda *_args:
        SimpleNamespace(version_no=0, source_changed=False, warnings=["历史对账单尚未建立明细"], items=[]))
    monkeypatch.setattr(finance_read_model.invoice_matches, "line_summary", lambda *_args: ([], []))

    class QueryRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    grouped = [
        [{"status": "DRAFT", "count": 1, "amount": Decimal("50")}],
        [],
    ]
    monkeypatch.setattr(tool_db, "execute", lambda _query: QueryRows(grouped.pop(0)))
    result = finance_read_model.read_reconciliation(tool_db, SimpleNamespace(id=7), SimpleNamespace(id=72))

    assert result["version_no"] == 0
    assert result["lines"] == []
    assert result["line_warnings"] == ["历史对账单尚未建立明细"]
    assert result["payment_precheck"]["max_new_payment_amount"] == Decimal("0")
    assert result["payment_precheck"]["blockers"] == ["对账单尚未确认", "当前没有已核验发票"]


def test_finance_reconciliation_tool_requires_all_read_permissions(tool_db, monkeypatch):
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: ["finance.reconciliations.read"])
    assert "finance_reconciliations.get_by_no" not in {
        item["name"] for item in tools.list_tools(tool_db, SimpleNamespace(id=7))
    }
    with pytest.raises(AuthorizationError):
        call(tool_db, name="finance_reconciliations.get_by_no", reconciliation_no="FR20261022000071")


def test_finance_reconciliation_lookup_reuses_detail_scope_check(monkeypatch):
    from app.modules.finance import service as finance_service

    user = SimpleNamespace(id=7)
    reconciliation = SimpleNamespace(id=71)
    scope_calls = []
    monkeypatch.setattr(finance_service, "get_reconciliation",
        lambda _db, actor, reconciliation_id: scope_calls.append((actor, reconciliation_id)) or reconciliation)
    db = SimpleNamespace(scalar=lambda _query: 71)

    assert finance_service.get_reconciliation_by_no(db, user, "FR20261022000071") is reconciliation
    assert scope_calls == [(user, 71)]


def test_supplier_tool_returns_exact_code_and_business_fields(tool_db, monkeypatch):
    from app.modules.suppliers import service as supplier_service

    supplier = SimpleNamespace(id=91, supplier_code="SUP-0001", supplier_name="示例供应商",
        status="ACTIVE", region="华东", business_scope="溶剂", cooperation_level="STRATEGIC",
        payment_terms="月结30天", default_lead_days=12)
    seen = []
    monkeypatch.setattr(supplier_service, "get_supplier_by_code",
        lambda _db, code: seen.append(code) or (supplier if code == supplier.supplier_code else None))

    result = call(tool_db, name="suppliers.get_by_code", supplier_code=supplier.supplier_code)

    assert result.total_rows == 1
    assert result.rows[0].supplier_name == "示例供应商"
    assert result.rows[0].payment_terms == "月结30天"
    assert result.sources[0].resource == "suppliers"
    assert seen == [supplier.supplier_code]
    assert call(tool_db, name="suppliers.get_by_code", supplier_code="SUP-UNKNOWN").total_rows == 0


def test_supplier_tool_requires_permission_and_rejects_extra_fields(tool_db, monkeypatch):
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: [])
    with pytest.raises(AuthorizationError):
        call(tool_db, name="suppliers.get_by_code", supplier_code="SUP-0001")
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: ["master.suppliers.read"])
    with pytest.raises(BusinessValidationError, match="参数"):
        call(tool_db, name="suppliers.get_by_code", supplier_code="SUP-0001", supplier_id=91)


def test_quality_acceptance_service_reuses_inspector_scope(tool_db, monkeypatch):
    from app.modules.quality_acceptances import service as acceptance_service

    tool_db.execute(text("""CREATE TABLE quality_acceptances (
        id INTEGER PRIMARY KEY, acceptance_no VARCHAR(32) NOT NULL, delivery_id INTEGER NOT NULL,
        inspector_id INTEGER NOT NULL, result VARCHAR(20) NOT NULL, inspection_time DATETIME,
        test_result JSON, certificate_complete SMALLINT NOT NULL, report_file_id INTEGER,
        conclusion VARCHAR(2000), created_at DATETIME, updated_at DATETIME)"""))
    tool_db.execute(text("""INSERT INTO quality_acceptances
        (id, acceptance_no, delivery_id, inspector_id, result, certificate_complete)
        VALUES (41, 'QA-OWN', 1, 7, 'PENDING', 0), (42, 'QA-OTHER', 2, 8, 'PASSED', 1)"""))
    tool_db.commit()
    monkeypatch.setattr(acceptance_service, "get_user_role_codes", lambda *_args: ["QUALITY"])

    visible = acceptance_service.get_acceptance_by_no(tool_db, SimpleNamespace(id=7), "QA-OWN")

    assert visible is not None and visible.id == 41
    assert acceptance_service.get_acceptance_by_no(tool_db, SimpleNamespace(id=7), "QA-OTHER") is None
    assert acceptance_service.get_acceptance_by_no(tool_db, SimpleNamespace(id=7), "QA-MISSING") is None


def test_http_routes_require_authentication_and_reject_extra_identity_fields():
    """检查 API 登录要求和顶层身份字段被请求 Schema 拒绝。"""
    app = FastAPI()
    app.include_router(router)
    allow_ai_workspace_permission(app)
    with TestClient(app) as client:
        assert client.get('/ai/agent/tools').status_code == 401
        assert client.post('/ai/agent/tools/execute', json={"tool": "inventory.query_available", "arguments": {"product_id": 1}}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: SimpleNamespace()
        response = client.post('/ai/agent/tools/execute', json={"tool": "inventory.query_available", "arguments": {}, "user_id": 9})
        assert response.status_code == 422


def test_http_catalog_and_both_result_schemas(tool_db):
    """经真实路由核验工具目录、两种输出 Schema 和 Decimal/日期 JSON 序列化。"""
    app = FastAPI()
    app.include_router(router)
    allow_ai_workspace_permission(app)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    app.dependency_overrides[get_db] = lambda: tool_db
    with TestClient(app) as client:
        catalog = client.get('/ai/agent/tools')
        assert catalog.status_code == 200
        assert {item['risk'] for item in catalog.json()} == {'READ_ONLY'}
        for name, arguments in [
            ('inventory.query_available', {'product_id': 1}),
            ('supplier_quotes.compare', {'product_id': 1, 'rfq_item_id': 11}),
        ]:
            response = client.post('/ai/agent/tools/execute', json={'tool': name, 'arguments': arguments})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['tool'] == name and result['sources']
            assert isinstance(result['rows'][0].get('quantity', result['rows'][0].get('unit_price')), str)


def test_product_lookup_returns_specs_and_escapes_sql_wildcards(tool_db):
    """名称/编码定位返回具体规格，用户输入百分号不能变成全目录通配查询。"""
    result = call(tool_db, name='catalog.search_products', keyword='P-ETH')
    assert result.total_rows == 1 and result.rows[0].model == '分析纯'
    assert result.sources[0].record_id == 1
    assert call(tool_db, name='catalog.search_products', keyword='%').total_rows == 0


def test_product_lookup_respects_product_read_permission(tool_db):
    """库存读取权限不自动包含主数据目录读取权限。"""
    with pytest.raises(AuthorizationError):
        call(tool_db, name='catalog.search_products', actor_id=8, keyword='乙醇')


def test_exact_product_code_resolves_prefix_ambiguity_without_guessing(tool_db):
    tool_db.execute(text("INSERT INTO md_products (id, product_name, status, product_code, model, packaging_spec, unit_id, chemical_id) VALUES (3, '测试乙醇', 'ACTIVE', 'P-ETH-ALT', '其他规格', '5kg', 1, 1)"))
    assert call(tool_db, name='catalog.search_products', keyword='测试乙醇').total_rows == 2
    alias_matches = call(tool_db, name="catalog.search_products", keyword="酒精")
    assert alias_matches.total_rows == 2
    assert {row.product_id for row in alias_matches.rows} == {1, 3}
    exact = call(tool_db, name='catalog.search_products', keyword='P-ETH')
    assert exact.total_rows == 1 and exact.rows[0].product_id == 1
    assert exact.sources[0].record_id == 1
    assert call(tool_db, name='catalog.search_products', keyword='P-OFF').total_rows == 0


@pytest.mark.parametrize("keyword", ["酒精", "乙醇俗名", "ETHANOL", "Ethyl alcohol"])
def test_product_lookup_matches_registered_chemical_aliases_and_english_name(tool_db, keyword):
    result = call(tool_db, name="catalog.search_products", keyword=keyword)

    assert result.total_rows == 1
    assert result.rows[0].product_id == 1
    assert result.sources[0].record_id == 1


def test_product_alias_match_is_exact_and_keeps_cas_and_code_rules(tool_db):
    assert call(tool_db, name="catalog.search_products", keyword="精").total_rows == 0
    assert call(tool_db, name="catalog.search_products", keyword="乙醇俗").total_rows == 0
    assert call(tool_db, name="catalog.search_products", keyword="64-17-5").rows[0].product_id == 1
    exact_code = call(tool_db, name="catalog.search_products", keyword="P-ETH")
    assert exact_code.total_rows == 1 and exact_code.rows[0].product_id == 1


def test_rfq_lookup_filters_requester_status_and_exact_number(tool_db):
    """可见询价定位按原询价范围过滤，并支持用户明确提供的编号。"""
    result = call(tool_db, name='supplier_quotes.find_rfq_items', product_id=1)
    assert [row.rfq_item_id for row in result.rows] == [11]
    assert call(tool_db, name='supplier_quotes.find_rfq_items', actor_id=10, product_id=1).total_rows == 2
    assert call(tool_db, name='supplier_quotes.find_rfq_items', actor_id=10, product_id=1, rfq_no='RFQ-OTHER').rows[0].rfq_item_id == 21
