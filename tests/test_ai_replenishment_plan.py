"""补货量建议：安全库存缺口、在途抵扣和权限裁剪。"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.ai import agent_tools, schema
from app.modules.products.model import Product
from app.modules.system.model import User


def test_tool_is_registered_and_task_requires_product_keyword():
    assert "inventory.replenishment_plan" in agent_tools.TOOLS
    with pytest.raises(ValueError):
        schema.Understanding(purpose="query", execution_mode="agent", tasks=["replenishment_plan"])
    decision = schema.Understanding(purpose="query", execution_mode="agent",
                                    tasks=["replenishment_plan"],
                                    slots={"product_keyword": "无水乙醇"})
    assert decision.agent_goal == "replenishment_plan"


def test_plan_computes_gap_and_formats_decimal(db_session):
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").limit(1))
    product.safety_stock_quantity = Decimal("900000")
    db_session.flush()

    result = agent_tools.replenishment_plan(
        db_session, user, schema.ReplenishmentPlanInput(product_id=product.id))

    expected = Decimal("900000") - Decimal(result.available_quantity) \
        - Decimal(result.incoming_purchase_quantity) - Decimal(result.incoming_replenishment_quantity)
    assert result.status == "SUGGESTED"
    assert Decimal(result.suggested_quantity) == max(Decimal(0), expected)
    assert result.safety_stock == "900000"
    assert "建议补货" in result.summary
    assert any("MOQ" in warning for warning in result.warnings)


def test_plan_without_safety_stock_is_read_only_no_threshold(db_session):
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").limit(1))
    product.safety_stock_quantity = None
    db_session.flush()

    result = agent_tools.replenishment_plan(
        db_session, user, schema.ReplenishmentPlanInput(product_id=product.id))

    assert result.status == "NO_THRESHOLD"
    assert result.suggested_quantity is None
    assert "未维护安全库存" in result.summary


def test_plan_without_incoming_permissions_adds_warnings(db_session, monkeypatch):
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").limit(1))
    product.safety_stock_quantity = Decimal("1")
    db_session.flush()
    monkeypatch.setattr(agent_tools, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(agent_tools, "get_user_permission_codes", lambda *_args: [])

    result = agent_tools.replenishment_plan(
        db_session, user, schema.ReplenishmentPlanInput(product_id=product.id))

    assert result.incoming_purchase_quantity == "0"
    assert result.incoming_replenishment_quantity == "0"
    assert any("采购订单读取权限" in warning for warning in result.warnings)
    assert any("补货申请读取权限" in warning for warning in result.warnings)


def test_agent_summary_and_finish_use_plan_result():
    from app.modules.ai import agent_runtime

    plan = {"tool": "inventory.replenishment_plan", "summary": "建议补货 10 升。"}
    agent_runtime._validate_finish_evidence("replenishment_plan", [
        {"tool": "inventory.replenishment_plan", "result": plan},
    ])
    assert agent_runtime._summary([{"tool": "inventory.replenishment_plan", "result": plan}]) == plan["summary"]
