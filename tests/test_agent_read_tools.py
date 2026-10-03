"""只读工具的真实查询、权限、报价可比性和无写入回归；使用隔离 SQLite 样本。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai import agent_tools as tools
from app.modules.ai.controller import router
from app.modules.inventory import service as inventory_service


@pytest.fixture
def tool_db(monkeypatch):
    """建立隔离业务样本和角色权限替身；查询执行真实 SQL，测试后销毁数据库。"""
    roles = {9: ["SYS_ADMIN"], 10: ["PROCUREMENT_MANAGER"]}
    permissions = {7: ["master.products.read", "warehouse.inventory.read", "procurement.rfqs.read"],
                   8: ["warehouse.inventory.read"], 10: ["master.products.read", "warehouse.inventory.read", "procurement.rfqs.read"]}
    monkeypatch.setattr(tools, "get_settings", lambda: SimpleNamespace(agent_enabled=True))
    monkeypatch.setattr(tools, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda _db, uid: permissions.get(uid, []))
    monkeypatch.setattr(inventory_service, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE md_products (id INTEGER PRIMARY KEY, product_name TEXT, status TEXT, product_code TEXT, model TEXT, packaging_spec TEXT, unit_id INTEGER)",
            "CREATE TABLE md_units (id INTEGER PRIMARY KEY, unit_name TEXT, status TEXT)",
            "CREATE TABLE warehouses (id INTEGER PRIMARY KEY, warehouse_name TEXT, manager_id INTEGER, status TEXT, warehouse_code TEXT, region TEXT, address TEXT, note TEXT, created_at DATETIME, updated_at DATETIME)",
            "CREATE TABLE inventory_batches (id INTEGER PRIMARY KEY, batch_no TEXT, expiry_date DATE)",
            "CREATE TABLE inventory_balances (id INTEGER PRIMARY KEY, warehouse_id INTEGER, batch_id INTEGER, product_id INTEGER, unit_id INTEGER, status TEXT, quantity NUMERIC, locked_quantity NUMERIC)",
            "CREATE TABLE rfqs (id INTEGER PRIMARY KEY, rfq_no TEXT, requester_id INTEGER, status TEXT)",
            "CREATE TABLE rfq_items (id INTEGER PRIMARY KEY, rfq_id INTEGER, product_id INTEGER, specification TEXT, technical_requirements TEXT)",
            "CREATE TABLE suppliers (id INTEGER PRIMARY KEY, supplier_name TEXT, status TEXT)",
            "CREATE TABLE supplier_quotes (id INTEGER PRIMARY KEY, rfq_id INTEGER, supplier_id INTEGER, quote_no TEXT, quote_version INTEGER, quote_date DATE, valid_until DATE, currency_code TEXT, status TEXT)",
            "CREATE TABLE supplier_quote_items (id INTEGER PRIMARY KEY, quote_id INTEGER, rfq_item_id INTEGER, unit_id INTEGER, supplier_model TEXT, tax_rate NUMERIC, unit_price NUMERIC, quoted_quantity NUMERIC, moq_quantity NUMERIC, moq_unit_id INTEGER, lead_days INTEGER)",
        ):
            conn.exec_driver_sql(ddl)
        for sql in (
            "INSERT INTO md_products VALUES (1, '测试乙醇', 'ACTIVE', 'P-ETH', '分析纯', '20kg', 1), (2, '停用产品', 'INACTIVE', 'P-OFF', NULL, NULL, 1)",
            "INSERT INTO md_units VALUES (1, '千克', 'ACTIVE'), (2, '升', 'ACTIVE'), (3, '停用单位', 'INACTIVE')",
            "INSERT INTO warehouses (id, warehouse_name, manager_id, status) VALUES (1, '本人仓库', 7, 'ACTIVE'), (2, '其他仓库', 8, 'ACTIVE'), (3, '公共仓库', NULL, 'ACTIVE'), (4, '停用仓库', NULL, 'INACTIVE')",
            "INSERT INTO inventory_batches VALUES (1, '批次A', '2020-01-01'), (2, '批次B', NULL)",
            "INSERT INTO inventory_balances VALUES (1, 1, 1, 1, 1, 'AVAILABLE', 100, 20), (2, 1, 2, 1, 1, 'FROZEN', 50, 0), (3, 2, 2, 1, 1, 'AVAILABLE', 999, 0), (4, 3, 2, 1, 2, 'AVAILABLE', 5, 0), (5, 4, 2, 1, 1, 'AVAILABLE', 888, 0)",
            "INSERT INTO rfqs VALUES (1, 'RFQ-OWN', 7, 'RESPONDING'), (2, 'RFQ-OTHER', 8, 'RESPONDING'), (3, 'RFQ-CLOSED', 7, 'CLOSED')",
            "INSERT INTO rfq_items VALUES (11, 1, 1, '分析纯', '原始条件'), (21, 2, 1, '分析纯', NULL), (31, 3, 1, '分析纯', NULL)",
        ):
            conn.exec_driver_sql(sql)
        for sid in range(1, 13):
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
        ]
        for qid, sid, version, price, currency, unit, model, tax, valid, status, quoted in samples:
            conn.exec_driver_sql("INSERT INTO supplier_quotes VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)",
                                 (qid, sid, f"Q-{qid}", version, quoted, valid, currency, status))
            conn.exec_driver_sql("INSERT INTO supplier_quote_items VALUES (?, ?, 11, ?, ?, ?, ?, 20, 5, 1, 3)",
                                 (qid, qid, unit, model, tax, price))
    with Session(engine) as session:
        yield session
    engine.dispose()


def call(db, name="inventory.query_available", actor_id=7, **arguments):
    """区分认证执行人与工具参数，使身份注入用例真正进入 Schema 校验。"""
    return tools.execute_tool(db, SimpleNamespace(id=actor_id), tools.ToolCall(tool=name, arguments=arguments))


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


def test_quote_revision_expiry_currency_unit_tax_and_model_boundaries(tool_db):
    """独立预期值核验报价有效性、版本选择及可比组排名。"""
    result = call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=11)
    assert result.total_rows == 7
    assert {row.quote_id: row.rank for row in result.rows} == {2: 2, 3: 1, 5: None, 6: None, 7: None, 8: None, 9: None}
    assert all(source.parent_id == 1 for source in result.sources)
    assert result.specification == "分析纯"
    assert result.model_dump(mode="json")["rows"][0]["unit_price"] == "10.000000"


def test_truncated_quotes_are_never_ranked_as_complete_comparison(tool_db):
    """不把截断后的局部候选误标为完整比价排名。"""
    result = call(tool_db, name="supplier_quotes.compare", product_id=1, rfq_item_id=11, limit=1)
    assert result.truncated and result.total_rows == 7
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


def test_http_routes_require_authentication_and_reject_extra_identity_fields():
    """检查 API 登录要求和顶层身份字段被请求 Schema 拒绝。"""
    app = FastAPI()
    app.include_router(router)
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


def test_rfq_lookup_filters_requester_status_and_exact_number(tool_db):
    """可见询价定位按原询价范围过滤，并支持用户明确提供的编号。"""
    result = call(tool_db, name='supplier_quotes.find_rfq_items', product_id=1)
    assert [row.rfq_item_id for row in result.rows] == [11]
    assert call(tool_db, name='supplier_quotes.find_rfq_items', actor_id=10, product_id=1).total_rows == 2
    assert call(tool_db, name='supplier_quotes.find_rfq_items', actor_id=10, product_id=1, rfq_no='RFQ-OTHER').rows[0].rfq_item_id == 21
