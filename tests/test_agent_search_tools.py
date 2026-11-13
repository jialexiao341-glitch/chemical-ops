"""采购订单与运营异常列表检索工具的契约回归。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import AuthorizationError, BusinessValidationError
from app.modules.ai_agent import agent_tools
from app.modules.ai_agent.schema import ExceptionSearchInput, PurchaseOrderSearchInput


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """仅为来源名称映射提供确定返回值。"""

    def __init__(self, rows=None):
        self.rows = rows or []

    def execute(self, _statement):
        return _Rows(self.rows)


def _tool_settings():
    return SimpleNamespace(agent_enabled=True, agent_tool_timeout_seconds=15)


def test_order_search_maps_list_rows_and_passes_filters(monkeypatch):
    """列表检索只输出摘要字段，并原样传递授权范围内的筛选条件。"""
    from app.modules.purchase_orders import service as order_service

    order = SimpleNamespace(
        id=7, po_no="PO20261021000001", supplier_id=3, status="ORDERED",
        order_date=date(2026, 10, 1), expected_arrival_date=date(2026, 10, 20),
        order_amount=Decimal("100.000000"), currency_code="CNY",
        items=[
            SimpleNamespace(received_quantity=Decimal("0"), order_quantity=Decimal("2")),
            SimpleNamespace(received_quantity=Decimal("2"), order_quantity=Decimal("2")),
        ],
    )
    calls = {}

    def fake_list_orders(_db, _user, **kwargs):
        calls.update(kwargs)
        return [order], 1

    monkeypatch.setattr(order_service, "list_orders", fake_list_orders)
    result = agent_tools.search_purchase_orders(
        _FakeDb([(3, "华东供应商")]), SimpleNamespace(id=1),
        PurchaseOrderSearchInput(supplier_keyword="华东", status="ORDERED", limit=10))

    assert calls["supplier_keyword"] == "华东"
    assert calls["status"] == "ORDERED"
    assert result.total_rows == 1 and result.truncated is False
    assert result.rows[0].supplier_name == "华东供应商"
    assert result.rows[0].item_count == 2 and result.rows[0].open_item_count == 1
    assert result.sources[0].record_id == 7


def test_exception_search_maps_list_rows_and_truncates_description(monkeypatch):
    """异常检索不返回任务评论、附件或处理人身份。"""
    from app.modules.operation_exceptions import service as exception_service

    exception = SimpleNamespace(
        id=11, exception_no="EX20261025000001", exception_type="OVERDUE", severity="HIGH",
        status="OPEN", description="x" * 600, due_at=None,
        created_at=datetime(2026, 10, 25, 9, 0),
        source_type="PURCHASE_ORDER", source_id=7, po_id=None,
    )

    def fake_list_exceptions(_db, _user, **kwargs):
        assert kwargs["severity"] == "HIGH"
        assert kwargs["keyword"] == "逾期"
        return [exception], 3

    monkeypatch.setattr(exception_service, "list_exceptions", fake_list_exceptions)
    result = agent_tools.search_exceptions(
        _FakeDb(), SimpleNamespace(id=1), ExceptionSearchInput(severity="HIGH", keyword="逾期", limit=2))

    assert result.total_rows == 3 and result.truncated is True
    assert len(result.rows[0].description) == 500
    assert result.rows[0].po_no is None
    assert result.sources[0].resource == "operation_exceptions"


def test_search_tools_require_reader_permissions(monkeypatch):
    """绕过能力目录直接执行时仍要经过当前 RBAC。"""
    monkeypatch.setattr(agent_tools, "get_settings", _tool_settings)
    monkeypatch.setattr(agent_tools, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(agent_tools, "get_user_permission_codes", lambda *_args: set())

    with pytest.raises(AuthorizationError):
        agent_tools.execute_tool(_FakeDb(), SimpleNamespace(id=1),
                                 agent_tools.ToolCall(tool="purchase_orders.search", arguments={}))
    with pytest.raises(AuthorizationError):
        agent_tools.execute_tool(_FakeDb(), SimpleNamespace(id=1),
                                 agent_tools.ToolCall(tool="exceptions.search", arguments={}))


def test_search_tools_reject_identity_and_unknown_fields(monkeypatch):
    """模型夹带身份或未登记字段时在进入 handler 前拒绝。"""
    monkeypatch.setattr(agent_tools, "get_settings", _tool_settings)
    monkeypatch.setattr(agent_tools, "get_user_role_codes", lambda *_args: ["SYS_ADMIN"])
    monkeypatch.setattr(agent_tools, "get_user_permission_codes", lambda *_args: set())

    with pytest.raises(BusinessValidationError, match="参数"):
        agent_tools.execute_tool(_FakeDb(), SimpleNamespace(id=1), agent_tools.ToolCall(
            tool="purchase_orders.search", arguments={"user_id": 1}))
    with pytest.raises(BusinessValidationError, match="参数"):
        agent_tools.execute_tool(_FakeDb(), SimpleNamespace(id=1), agent_tools.ToolCall(
            tool="exceptions.search", arguments={"sql": "SELECT 1"}))