"""统一路由的契约、上下文与执行边界；脚本化模型不代表真实语义准确率。"""

import asyncio
import json
from types import SimpleNamespace

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import BusinessValidationError
from app.modules.ai import llm, routing, service


@pytest.mark.parametrize("question,route", [("/help", "capability"), ("你好", "greeting"), ("取消查询", "cancel")])
def test_explicit_commands_skip_model(monkeypatch, question, route):
    async def forbidden(*args, **kwargs):
        raise AssertionError("明确控制命令不应调用模型")
    monkeypatch.setattr(llm, "chat", forbidden)
    assert asyncio.run(routing.understand(question)).route == route


@pytest.mark.parametrize("question,payload,route", [
    ("你好，查乙醇库存", {"purpose": "query", "tasks": ["inventory"], "slots": {"product_keyword": "乙醇"}}, "agent"),
    ("查 64-17-5 的库存", {"purpose": "query", "tasks": ["inventory"], "slots": {"product_keyword": "64-17-5"}}, "agent"),
    ("库存查询支持哪些筛选条件？", {"purpose": "capability"}, "capability"),
    ("库存不足怎么处理？", {"purpose": "guidance"}, "guidance"),
    ("查库存，不用比较报价", {"purpose": "query", "tasks": ["inventory", "quotes"], "excluded_tasks": ["quotes"]}, "agent"),
    ("查供应商总数", {"purpose": "query", "tasks": ["analytics"]}, "query"),
    ("把时间改成上个月", {"purpose": "query", "dialogue_action": "modify", "tasks": ["analytics"]}, "query"),
    ("查乙醇库存并比较报价", {"purpose": "query", "tasks": ["inventory", "quotes"]}, "agent"),
    ("查乙醇闪点并查库存", {"purpose": "query", "tasks": ["document", "inventory"]}, "clarify"),
])
def test_structured_model_result_controls_route_and_keeps_context(monkeypatch, question, payload, route):
    context = {"query_plan": {"dataset": "purchase_orders"}, "memory": {"goal": {"intent": "inventory_query"}}}
    async def model(request, settings, **kwargs):
        assert json.loads(request.messages[0].content)["question"] == question
        assert json.loads(request.messages[0].content)["context"] == context
        assert settings.llm_temperature == 0
        assert kwargs["interpret_only"] is True
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["strict"] is True
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
    monkeypatch.setattr(llm, "chat", model)
    decision = asyncio.run(routing.understand(question, context))
    assert decision.route == route
    assert not set(decision.tasks) & set(decision.excluded_tasks)


@pytest.mark.parametrize("value", ["not json", '{}', '{"purpose":"query"}',
    '{"purpose":"query","tasks":["sql"]}',
    '{"purpose":"query","tasks":["inventory"],"slots":{"product_id":1}}',
    '{"purpose":"query","tasks":["inventory"],"slots":{"limit":-1}}'])
def test_invalid_model_output_clarifies_without_keyword_fallback(monkeypatch, value):
    async def model(*args, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content=value))
    monkeypatch.setattr(llm, "chat", model)
    decision = asyncio.run(routing.understand("查乙醇库存"))
    assert decision.route == "clarify" and decision.tasks == [] and decision.question


def test_model_failure_clarifies(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(llm, "chat", unavailable)
    assert asyncio.run(routing.understand("查乙醇库存")).route == "clarify"


def test_route_ticket_binds_user_question_conversation_and_signature():
    decision = routing.Understanding(purpose="query", tasks=["inventory"])
    token = routing.issue_ticket(decision, 7, "查乙醇库存", 9)
    assert routing.read_ticket(token, 7, "查乙醇库存", 9) == decision
    for user_id, question, cid in [(8, "查乙醇库存", 9), (7, "查甲醇库存", 9), (7, "查乙醇库存", 10)]:
        with pytest.raises(BusinessValidationError):
            routing.read_ticket(token, user_id, question, cid)
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["exp"] = 1
    settings = get_settings()
    expired = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(BusinessValidationError):
        routing.read_ticket(expired, 7, "查乙醇库存", 9)


def test_supplied_ids_and_confidence_are_not_understanding_contract():
    with pytest.raises(ValidationError):
        routing.Understanding(purpose="query", tasks=["inventory"], confidence=1, product_id=123)


def test_route_endpoint_permissions_and_foreign_context(client, db_session, monkeypatch):
    from app.core.auth import get_current_user
    from app.main import app
    from app.modules.ai.model import AIConversation
    from app.modules.system.model import User
    from sqlalchemy import select
    from tests.test_rbac_separation import as_demo_role

    buyer = db_session.scalar(select(User).where(User.username == "buyer"))
    owner = db_session.scalar(select(User).where(User.username == "system_admin"))
    conversation = AIConversation(user_id=owner.id, title="foreign", business_scene="GENERAL", status="ACTIVE")
    db_session.add(conversation); db_session.flush()
    calls = []
    async def understand(question, context):
        calls.append(question)
        return routing.Understanding(purpose="query", tasks=["inventory"])
    monkeypatch.setattr(routing, "understand", understand)
    app.dependency_overrides[get_current_user] = lambda: buyer
    response = client.post("/api/v1/ai/route", json={"question": "查乙醇库存"})
    assert response.status_code == 200 and response.json()["route"] == "agent"
    routing.read_ticket(response.json()["route_token"], buyer.id, "查乙醇库存", None)
    response = client.post("/api/v1/ai/route", json={"question": "查库存", "conversation_id": conversation.id})
    assert response.status_code == 400 and len(calls) == 1
    with as_demo_role(db_session, "SUPPLIER_PORTAL"):
        response = client.post("/api/v1/ai/route", json={"question": "查库存"})
    assert response.status_code == 403 and len(calls) == 1
