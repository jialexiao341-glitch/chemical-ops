"""统一路由的契约、上下文与执行边界；脚本化模型不代表真实语义准确率。"""

import json
from types import SimpleNamespace

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import BusinessValidationError
from app.core.observability import metrics
from app.modules.ai import llm, routing, service
from app.modules.ai.catalog import catalog_prompt


from app.modules.ai.schema import Slots


@pytest.mark.parametrize("value,expected", [
    (None, False), (False, False), (True, True), (0, False), (1, True),
    ("false", False), ("true", True), ("否", False), ("是", True), ("", False),
])
def test_slots_coerces_common_boolean_tokens(value, expected):
    """模型偶发返回 null 或中英文布尔词；明确表达可接受，未知值仍拒绝。"""
    assert Slots(aggregate_products=value).aggregate_products is expected


def test_slots_rejects_ambiguous_boolean_token():
    with pytest.raises(ValidationError):
        Slots(aggregate_products="可能")


def test_understanding_and_sub_tasks_accept_null_slots_but_reject_strings():
    decision = routing.Understanding.model_validate_json(json.dumps({
        "purpose": "query", "execution_mode": "query", "tasks": ["analytics"], "slots": None,
        "sub_tasks": [{"id": "t1", "kind": "analytics", "question": "统计采购订单数量", "slots": None}],
    }), strict=True)
    assert decision.slots == Slots() and decision.sub_tasks[0].slots == Slots()
    with pytest.raises(ValidationError):
        routing.Understanding.model_validate_json(json.dumps({
            "purpose": "query", "execution_mode": "agent", "tasks": ["inventory"], "slots": "{}",
        }), strict=True)


@pytest.mark.parametrize("raw,expected_limit,expected_unit", [
    ('{"limit": "20", "unit": "  吨 "}', 20, "吨"),
    ('{"limit": 20.0}', 20, None),
])
def test_slots_accepts_lossless_limit_and_trimmed_unit(raw, expected_limit, expected_unit):
    slots = Slots.model_validate_json(raw)
    assert (slots.limit, slots.unit) == (expected_limit, expected_unit)


@pytest.mark.parametrize("raw", ['{"limit": "很多"}', '{"limit": true}', '{"limit": 0}', '{"unit": 5}'])
def test_slots_rejects_unrecoverable_limit_and_unknown_unit(raw):
    with pytest.raises(ValidationError):
        Slots.model_validate_json(raw)


@pytest.mark.parametrize("token,expected", [
    ("2026/11/11", "2026-11-11"), ("2026.11.11", "2026-11-11"),
    ("2026年11月11日", "2026-11-11"), ("2026-11-11T23:30:00+08:00", "2026-11-11"),
])
def test_slots_accepts_common_date_separators(token, expected):
    assert Slots(date_from=token).date_from.isoformat() == expected


@pytest.mark.parametrize("token", ["2026/13/01", "2026-02-30", "下个月", "2026/11"])
def test_slots_still_rejects_invalid_calendar_dates(token):
    with pytest.raises(ValidationError):
        Slots(date_from=token)


def _run_immediate(coroutine):
    """运行无 I/O 的模型替身协程，避免测试依赖 Windows loop socketpair。"""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("路由测试替身不应挂起等待")


def test_purchase_draft_intent_is_a_dedicated_preview_route():
    decision = routing.Understanding(purpose="purchase_draft")
    assert decision.route == "purchase_draft"
    assert not decision.tasks and not decision.sub_tasks


@pytest.mark.parametrize("purpose,request_no,action_fields", [
    ("purchase_update", "PR20261022000001", {"purpose": "调整实验用途"}),
    ("purchase_submit", "PR20261022000002", None),
    ("rfq_draft", "PR20261022000003", {"supplier_codes": ["SUP-001"]}),
])
def test_write_intents_are_proposal_only_and_bind_an_exact_source_request(purpose, request_no, action_fields):
    decision = routing.Understanding.model_validate({
        "purpose": purpose, "execution_mode": "none", "slots": {"request_no": request_no},
        "action_fields": action_fields,
    })
    assert decision.route == purpose
    assert decision.slots.request_no == request_no
    assert decision.tasks == []
    assert decision.sub_tasks == []


@pytest.mark.parametrize("purpose,action_fields", [
    ("purchase_update", {"purpose": "x"}), ("purchase_submit", None),
    ("rfq_draft", {"supplier_codes": ["SUP-001"]}),
])
def test_write_intents_without_exact_request_number_are_rejected(purpose, action_fields):
    with pytest.raises(ValidationError):
        routing.Understanding.model_validate({"purpose": purpose, "execution_mode": "none", "action_fields": action_fields})


def test_inventory_aggregation_is_carried_as_a_structured_slot():
    decision = routing.Understanding.model_validate({
        "purpose": "query",
        "tasks": ["inventory"],
        "execution_mode": "agent",
        "slots": {"aggregate_products": True},
    })

    assert decision.route == "agent"
    assert decision.slots.aggregate_products is True


@pytest.mark.parametrize("purpose,mode,tasks,subtasks,expected", [
    ("query", "agent", ["inventory"], [], "agent"),
    ("query", "agent", ["inventory", "quotes"], [], "agent"),
    ("query", "agent", ["purchase_request"], [], "agent"),
    ("query", "agent", ["order_trace"], [], "agent"),
    ("query", "agent", ["quality_acceptance"], [], "agent"),
    ("query", "batch", ["inventory"], ["inventory", "inventory"], "batch"),
    ("query", "batch", ["analytics"], ["analytics", "analytics"], "batch"),
    ("query", "batch", ["document"], ["document", "document"], "batch"),
    ("query", "query", ["analytics"], ["analytics"], "query"),
    ("query", "document", ["document"], ["document"], "document"),
    ("clarify", "none", [], [], "clarify"),
    ("purchase_draft", "none", [], [], "purchase_draft"),
])
def test_execution_mode_is_explicit_and_controls_route(purpose, mode, tasks, subtasks, expected):
    payload = {
        "purpose": purpose,
        "execution_mode": mode,
        "tasks": tasks,
        "slots": {"acceptance_no": "QA20261022000001"} if "quality_acceptance" in tasks else {},
        "sub_tasks": [
            {"id": f"t{i}", "kind": kind, "question": f"查询任务{i}"}
            for i, kind in enumerate(subtasks, 1)
        ],
    }
    decision = routing.Understanding.model_validate(payload)
    assert decision.route == expected


@pytest.mark.parametrize("payload", [
    {"purpose": "query", "tasks": ["inventory"]},
    {"purpose": "query", "execution_mode": "none", "tasks": ["inventory"]},
    {"purpose": "query", "execution_mode": "agent", "tasks": ["inventory"],
     "sub_tasks": [{"id": "t1", "kind": "inventory", "question": "乙醇库存"}]},
    {"purpose": "query", "execution_mode": "batch", "tasks": ["inventory"],
     "sub_tasks": [{"id": "t1", "kind": "inventory", "question": "乙醇库存"}]},
    {"purpose": "query", "execution_mode": "batch", "tasks": ["inventory"],
     "sub_tasks": [{"id": f"t{i}", "kind": "inventory", "question": f"产品{i}库存"} for i in range(1, 8)]},
    {"purpose": "query", "execution_mode": "batch", "tasks": ["inventory"],
     "sub_tasks": [{"id": "t1", "kind": "inventory", "question": "乙醇库存"},
                   {"id": "t2", "kind": "quotes", "question": "甲醇报价"}]},
    {"purpose": "query", "execution_mode": "agent", "tasks": ["analytics"]},
    {"purpose": "query", "execution_mode": "query", "tasks": ["analytics", "inventory"],
     "sub_tasks": [{"id": "t1", "kind": "analytics", "question": "订单数"}]},
    {"purpose": "query", "execution_mode": "document", "tasks": ["document"]},
    {"purpose": "query", "execution_mode": "batch", "tasks": ["purchase_request"],
     "sub_tasks": [{"id": "t1", "kind": "purchase_request", "question": "读取申请 PR20261022000001"},
                   {"id": "t2", "kind": "purchase_request", "question": "读取申请 PR20261022000002"}]},
    {"purpose": "query", "execution_mode": "agent", "tasks": ["purchase_request", "inventory"]},
    {"purpose": "query", "execution_mode": "agent", "tasks": ["quality_acceptance"]},
    {"purpose": "greeting", "execution_mode": "agent"},
])
def test_invalid_execution_mode_combinations_are_rejected(payload):
    with pytest.raises(ValidationError):
        routing.Understanding.model_validate(payload)


@pytest.mark.parametrize("kind,slot,number,intent", [
    ("purchase_request", "request_no", "PR20261022000001", "purchase_request_query"),
    ("order_trace", "po_no", "PO-26001", "purchase_order_trace"),
    ("quality_acceptance", "acceptance_no", "QA20261022000001", "quality_acceptance_query"),
])
def test_agent_numbered_read_tasks_keep_exact_identifier_slot(kind, slot, number, intent):
    decision = routing.Understanding.model_validate({
        "purpose": "query", "execution_mode": "agent", "tasks": [kind],
        "slots": {slot: number},
    })
    assert decision.agent_goal == intent
    assert getattr(decision.slots, slot) == number


def test_routing_catalog_exposes_deterministic_derived_outputs():
    capabilities = json.loads(catalog_prompt())
    overdue = capabilities["overdue_unfulfilled_orders"]

    assert overdue["derived_outputs"] == [
        "per_order_overdue_days",
        "supplier_order_count",
        "supplier_unfulfilled_quantity_by_unit",
    ]


@pytest.mark.parametrize("question,route", [("/help", "capability"), ("你好", "greeting"), ("取消查询", "cancel")])
def test_explicit_commands_skip_model(monkeypatch, question, route):
    async def forbidden(*args, **kwargs):
        raise AssertionError("明确控制命令不应调用模型")
    monkeypatch.setattr(llm, "chat", forbidden)
    assert _run_immediate(routing.understand(question)).route == route


@pytest.mark.parametrize("question,payload,route", [
    ("我需要采购乙醇 12 升用于实验", {"purpose": "purchase_draft"}, "purchase_draft"),
    ("你好，查乙醇库存", {"purpose": "query", "execution_mode": "agent", "tasks": ["inventory"], "slots": {"product_keyword": "乙醇"}}, "agent"),
    ("查 64-17-5 的库存", {"purpose": "query", "execution_mode": "agent", "tasks": ["inventory"], "slots": {"product_keyword": "64-17-5"}}, "agent"),
    ("库存查询支持哪些筛选条件？", {"purpose": "capability"}, "capability"),
    ("库存不足怎么处理？", {"purpose": "guidance"}, "guidance"),
    ("查库存，不用比较报价", {"purpose": "query", "execution_mode": "agent", "tasks": ["inventory", "quotes"], "excluded_tasks": ["quotes"]}, "agent"),
    ("查供应商总数", {"purpose": "query", "execution_mode": "query", "tasks": ["analytics"], "sub_tasks": [{"id": "t1", "kind": "analytics", "question": "查供应商总数"}]}, "query"),
    ("把时间改成上个月", {"purpose": "query", "execution_mode": "query", "dialogue_action": "modify", "tasks": ["analytics"], "sub_tasks": [{"id": "t1", "kind": "analytics", "question": "查上个月"}]}, "query"),
    ("查乙醇库存并比较报价", {"purpose": "query", "execution_mode": "agent", "tasks": ["inventory", "quotes"]}, "agent"),
    ("查乙醇闪点并查库存", {"purpose": "clarify", "execution_mode": "none"}, "clarify"),
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
    decision = _run_immediate(routing.understand(question, context))
    assert decision.route == route
    assert not set(decision.tasks) & set(decision.excluded_tasks)


@pytest.mark.parametrize("value", ["not json", '{}', '{"purpose":"query"}',
    '{"purpose":"query","tasks":["sql"]}',
    '{"purpose":"query","tasks":["inventory"],"slots":{"product_id":1}}',
    '{"purpose":"query","tasks":["inventory"],"slots":{"limit":-1}}'])
def test_invalid_model_output_fails_without_keyword_fallback(monkeypatch, value):
    async def model(*args, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content=value))
    monkeypatch.setattr(llm, "chat", model)
    with pytest.raises(routing.IntentRecognitionError) as failure:
        _run_immediate(routing.understand("查乙醇库存"))
    assert failure.value.code == "INTENT_SCHEMA_ERROR"


@pytest.mark.parametrize("content", [
    '说明文字\n```json\n{"purpose":"query","execution_mode":"agent","tasks":["inventory"]}\n```',
    '{"purpose":"query","execution_mode":"agent","tasks":["inventory"],"slots":{"product_keyword":"乙醇"',
])
def test_fenced_or_truncated_model_output_is_repaired_before_validation(monkeypatch, content):
    calls = []
    async def model(*args, **kwargs):
        calls.append(kwargs['system_prompt'])
        return SimpleNamespace(message=SimpleNamespace(content=content))
    monkeypatch.setattr(llm, "chat", model)
    decision = _run_immediate(routing.understand("查乙醇库存"))
    assert decision.route == "agent" and decision.tasks == ["inventory"]
    assert len(calls) == 1  # 可修复的输出不额外消耗一次生成


def test_schema_error_is_counted_for_monitoring(monkeypatch):
    async def model(*args, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content='{"purpose":"query","tasks":["sql"]}'))
    monkeypatch.setattr(llm, "chat", model)
    with pytest.raises(routing.IntentRecognitionError):
        _run_immediate(routing.understand("查乙醇库存"))
    rendered = metrics.render_prometheus()
    assert 'chemicalops_llm_schema_errors_total{kind="schema_violation",stage="routing"}' in rendered


def test_model_failure_does_not_become_business_clarification(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(llm, "chat", unavailable)
    with pytest.raises(routing.IntentRecognitionError) as failure:
        _run_immediate(routing.understand("查乙醇库存"))
    assert failure.value.code == "INTENT_SERVICE_ERROR"
    assert "无需补充" in str(failure.value) and "尚未执行" in str(failure.value)


def test_provider_rejection_is_reported_as_technical_failure(monkeypatch):
    async def rejected(*args, **kwargs):
        raise BusinessValidationError("AI 服务拒绝了请求（HTTP 400），请检查模型接口、请求参数和结构化输出配置")
    monkeypatch.setattr(llm, "chat", rejected)
    with pytest.raises(routing.IntentRecognitionError) as failure:
        _run_immediate(routing.understand("统计本月逾期未交订单及关联库存"))
    assert "HTTP 400" in str(failure.value) and "尚未执行查询" in str(failure.value)


def test_root_contract_repair_explains_the_violated_rule(monkeypatch):
    calls = []
    async def model(*args, **kwargs):
        calls.append(kwargs['system_prompt'])
        subtasks = [] if len(calls) == 1 else [{"id": "t1", "kind": "analytics", "question": "统计订单及关联库存"}]
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "purpose": "query", "execution_mode": "query", "tasks": ["analytics"], "sub_tasks": subtasks,
        })))
    monkeypatch.setattr(llm, "chat", model)
    result = _run_immediate(routing.understand("统计订单及关联库存"))
    assert result.route == "query"
    assert "query 模式必须包含一个 analytics 子任务" in calls[1]


def test_invalid_six_task_contract_is_regenerated_before_execution(monkeypatch):
    calls = []
    async def model(request, settings, **kwargs):
        calls.append(kwargs['system_prompt'])
        tasks = [{"id": f"t{i}", "kind": "analytics", "question": f"统计第{i}类单据数量"} for i in range(1, 7)]
        payload = {"purpose": "query", "execution_mode": "batch", "tasks": ["analytics"] * (6 if len(calls) == 1 else 1), "sub_tasks": tasks}
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
    monkeypatch.setattr(llm, "chat", model)
    result = _run_immediate(routing.understand("分别统计六类单据数量"))
    assert result.route == "batch" and len(result.sub_tasks) == 6
    assert len(calls) == 2 and "错误位置" in calls[1]


def test_incomplete_model_response_is_regenerated_once(monkeypatch):
    calls = []
    async def model(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise BusinessValidationError("AI 服务返回了无法识别的结果")
        return SimpleNamespace(message=SimpleNamespace(content='{"purpose":"query","execution_mode":"query","tasks":["analytics"],"sub_tasks":[{"id":"t1","kind":"analytics","question":"统计采购订单数量"}]}'))
    monkeypatch.setattr(llm, "chat", model)
    assert _run_immediate(routing.understand("统计采购订单数量")).route == "query"
    assert len(calls) == 2


def test_route_ticket_binds_user_question_conversation_and_signature():
    decision = routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"])
    token = routing.issue_ticket(decision, 7, "查乙醇库存", 9, pending_state_id="a" * 32)
    assert routing.read_ticket(token, 7, "查乙醇库存", 9) == decision
    assert routing.read_ticket_pending_state_id(token) == "a" * 32
    for user_id, question, cid in [(8, "查乙醇库存", 9), (7, "查甲醇库存", 9), (7, "查乙醇库存", 10)]:
        with pytest.raises(BusinessValidationError):
            routing.read_ticket(token, user_id, question, cid)
    payload = jwt.decode(token, options={"verify_signature": False})
    legacy_payload = dict(payload)
    legacy_payload.pop("contract_version", None)
    legacy = jwt.encode(legacy_payload, get_settings().jwt_secret_key, algorithm=get_settings().jwt_algorithm)
    with pytest.raises(BusinessValidationError):
        routing.read_ticket(legacy, 7, "查乙醇库存", 9)
    payload["contract_version"] = "999"
    mismatched = jwt.encode(payload, get_settings().jwt_secret_key, algorithm=get_settings().jwt_algorithm)
    with pytest.raises(BusinessValidationError):
        routing.read_ticket(mismatched, 7, "查乙醇库存", 9)
    payload.pop("contract_version", None)
    payload["exp"] = 1
    settings = get_settings()
    expired = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(BusinessValidationError):
        routing.read_ticket(expired, 7, "查乙醇库存", 9)


def test_supplied_ids_and_confidence_are_not_understanding_contract():
    with pytest.raises(ValidationError):
        routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"], confidence=1, product_id=123)


def test_route_endpoint_permissions_and_foreign_context(client, db_session, monkeypatch):
    from app.core.auth import get_current_user
    from app.main import app
    from app.modules.ai.model import AIConversation
    from app.modules.system.model import User
    from sqlalchemy import select
    from tests.test_rbac_separation import as_demo_role

    buyer = db_session.scalar(select(User).where(User.username == "BuyerUser"))
    owner = db_session.scalar(select(User).where(User.username == "SystemAdmin"))
    conversation = AIConversation(user_id=owner.id, title="foreign", business_scene="GENERAL", status="ACTIVE")
    db_session.add(conversation); db_session.flush()
    calls = []
    async def understand(question, context, **kwargs):
        calls.append(question)
        return routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"])
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
