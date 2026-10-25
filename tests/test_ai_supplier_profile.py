"""供应商 360：跨模块汇总、权限裁剪与工具/Agent 契约。"""

import pytest
from sqlalchemy import select

from app.core.errors import AuthorizationError, BusinessValidationError
from app.modules.ai import agent_tools, schema
from app.modules.ai import supplier_profile as profile_module
from app.modules.ai.schema import ToolCall
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User


def _supplier_code(db_session) -> str:
    supplier = db_session.scalar(select(Supplier).order_by(Supplier.id).limit(1))
    assert supplier is not None
    return supplier.supplier_code


def test_tool_is_registered_and_requires_supplier_code():
    assert "suppliers.profile" in agent_tools.TOOLS
    with pytest.raises(ValueError):
        schema.Understanding(purpose="query", execution_mode="agent",
                             tasks=["supplier_profile"])
    decision = schema.Understanding(purpose="query", execution_mode="agent",
                                    tasks=["supplier_profile"],
                                    slots={"supplier_code": "SUP-26001"})
    assert decision.agent_goal == "supplier_profile"


def test_profile_aggregates_visible_sections(db_session):
    code = _supplier_code(db_session)
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    result = agent_tools.execute_tool(db_session, user, ToolCall(
        tool="suppliers.profile", arguments={"supplier_code": code}))
    stages = [section["stage"] for section in result.sections]
    assert stages == ["订单", "到货", "质量验收", "运营异常", "财务对账", "发票", "付款"]
    assert all(section["status"] != "NO_PERMISSION" for section in result.sections)
    assert result.answer.startswith(f"供应商 {code}")
    assert "以上汇总只反映当前权限范围" in result.answer


def test_profile_hides_sections_without_permission(db_session, monkeypatch):
    monkeypatch.setattr(profile_module, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(profile_module, "get_user_permission_codes", lambda *_args: ["master.suppliers.read"])
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    result = profile_module.build_supplier_profile(db_session, user, _supplier_code(db_session))
    assert all(section["status"] == "NO_PERMISSION" for section in result.sections)
    assert result.answer.endswith(
        "当前账号只能读取供应商主数据，无法查看订单、到货、质量、异常或财务汇总。\n"
        "以上汇总只反映当前权限范围内的记录，不代表供应商全量表现。")


def test_profile_unknown_code_returns_no_business_data(db_session):
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    result = profile_module.build_supplier_profile(db_session, user, "SUP-NOT-EXIST")
    assert result.sections == []
    assert "没有找到供应商编码" in result.answer


def test_history_rejects_revoked_stage_permissions(monkeypatch):
    from types import SimpleNamespace

    from app.modules.ai import agent_runtime

    monkeypatch.setattr(agent_runtime.tools, "list_tools", lambda *_args: [{"name": "suppliers.profile"}])
    monkeypatch.setattr(agent_runtime.tools, "accessible_warehouse_ids", lambda *_args: None)
    monkeypatch.setattr(agent_runtime.tools, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(agent_runtime.tools, "get_user_permission_codes",
                        lambda *_args: ["master.suppliers.read"])
    trace = [{
        "status": "SUCCEEDED", "action": "call_tool", "tool": "suppliers.profile", "arguments": {},
        "result": {"sections": [{"stage": "订单", "status": "AVAILABLE"}]},
    }]
    with pytest.raises(AuthorizationError, match="分段读取权限"):
        agent_runtime._check_trace_access(None, SimpleNamespace(id=7), trace)


def test_agent_finish_and_summary_use_profile_tool():
    from app.modules.ai import agent_runtime

    profile_result = {"tool": "suppliers.profile", "answer": "供应商 SUP-26001：订单 1 笔。"}
    agent_runtime._validate_finish_evidence("supplier_profile", [
        {"tool": "suppliers.profile", "result": profile_result},
    ])
    assert agent_runtime._summary([{"tool": "suppliers.profile", "result": profile_result}]) == profile_result["answer"]
    with pytest.raises(BusinessValidationError, match="INCOMPLETE_TASK"):
        agent_runtime._validate_finish_evidence("supplier_profile", [
            {"tool": "suppliers.get_by_code", "result": {}},
        ])
