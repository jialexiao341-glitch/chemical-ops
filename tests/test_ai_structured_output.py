"""模型侧 Schema 与服务端 Pydantic 校验同源，非法结构不能进入执行阶段。"""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai import llm, service, routing, text2sql
from app.modules.ai.schema import AIChatMessage, AIChatRequest
from app.modules.ai.schema import schema_response_format
from app.modules.ai.catalog import CATALOG
from app.modules.ai.agent_prompt import text2sql_plan_prompt


@pytest.mark.parametrize("model", [routing.Understanding, text2sql.QueryPlan])
def test_generated_schema_closes_every_object_and_requires_explicit_fields(model):
    format = schema_response_format(model, "contract")
    assert format["type"] == "json_schema" and format["json_schema"]["strict"] is True
    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(format["json_schema"]["schema"])


def test_routing_action_schema_has_explicit_properties_and_nullable_branch_types():
    schema = schema_response_format(routing.Understanding, "route")["json_schema"]["schema"]
    fields = schema["properties"]["action_fields"]["anyOf"][0]
    assert fields["type"] == "object"
    assert {"supplier_codes", "quote_deadline", "purpose", "items"} <= fields["properties"].keys()
    assert all("type" in branch for branch in schema["properties"]["action_fields"]["anyOf"])
    with pytest.raises(ValidationError):
        routing.Understanding.model_validate({
            "purpose": "purchase_update", "slots": {"request_no": "PR-001"},
            "action_fields": {"arbitrary_write": "forbidden"},
        })


def test_routing_strict_action_null_placeholders_do_not_expand_a_proposal():
    decision = routing.Understanding.model_validate({
        "purpose": "rfq_draft", "slots": {"request_no": "PR-001"},
        "action_fields": {"supplier_codes": ["SUP-001"], "purpose": None, "items": None},
    })
    assert decision.action_fields == {"supplier_codes": ["SUP-001"]}


def test_json_object_uses_chat_completions_response_format(monkeypatch):
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(service.chat(
        AIChatRequest(messages=[AIChatMessage(role="user", content="JSON object mock")]),
        Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=0),
        response_format={"type": "json_object"}, interpret_only=True))
    assert result.message.content == '{"ok":true}'
    assert payloads[0]["response_format"] == {"type": "json_object"}


def test_plan_schema_contains_slot_semantics_and_dataset_whitelists():
    schema = schema_response_format(text2sql.QueryPlan, "query_plan")["json_schema"]["schema"]
    assert all(field.get("description") for field in schema["properties"].values())
    for field, attribute in [("metric", "metrics"), ("time_field", "times"), ("group_by", "dimensions")]:
        mapping = json.loads(schema["properties"][field]["description"].split("各数据集允许值：")[1])
        assert mapping == {key: sorted(getattr(spec, attribute)) for key, spec in CATALOG.items()}
    filter_schema = schema["$defs"]["QueryFilter"]["properties"]
    mapping = json.loads(filter_schema["field"]["description"].split("各数据集允许值：")[1])
    assert mapping == {key: sorted(spec.filters) for key, spec in CATALOG.items()}
    assert "PAID" in filter_schema["value"]["description"]
    assert "supplier" in schema["properties"]["group_by"]["description"]
    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 100
    prompt = text2sql_plan_prompt("")
    assert "QueryPlan JSON Schema" in prompt
    assert "purchase_orders" not in prompt and "supplier_name" not in prompt and "PAID" not in prompt


def test_date_schema_uses_supported_pattern_and_pydantic_checks_calendar():
    schema = schema_response_format(text2sql.QueryPlan, "query_plan")["json_schema"]["schema"]
    date_schema = schema["properties"]["date_from"]["anyOf"][0]
    assert "format" not in date_schema
    assert date_schema["pattern"] == r"^\d{4}-\d{2}-\d{2}$"
    plan = text2sql.QueryPlan.model_validate_json(
        '{"dataset":"purchase_orders","metric":"count","date_from":"2026-10-01"}', strict=True)
    assert plan.date_from.isoformat() == "2026-10-01"
    with pytest.raises(ValidationError):
        text2sql.QueryPlan.model_validate_json(
            '{"dataset":"purchase_orders","metric":"count","date_from":"2026-02-30"}', strict=True)


@pytest.mark.parametrize("dates", [
    {"date_from": "2026-10-10", "date_to": "2026-10-01"},
    {"date_from": "2026-10-01", "time_field": None},
])
def test_query_dates_reject_inverted_ranges_or_missing_time_field(dates):
    with pytest.raises(ValidationError):
        text2sql.QueryPlan.model_validate_json(json.dumps(
            {"dataset": "purchase_orders", "metric": "count", **dates}), strict=True)


@pytest.mark.parametrize("patch", [
    {"dataset": "sys_users"}, {"metric": "execute_sql"}, {"sql": "SELECT * FROM sys_users"},
    {"limit": True}, {"limit": "20"}, {"group_by": ["supplier", "status"]},
    {"filters": [{"field": "password", "value": "x"}]},
])
def test_query_plan_rejects_extra_fields_invalid_enums_and_coercion(patch):
    payload = {"dataset": "purchase_orders", "metric": "count", **patch}
    with pytest.raises(ValidationError):
        text2sql.QueryPlan.model_validate_json(json.dumps(payload), strict=True)


@pytest.mark.parametrize("base,expected_path", [("https://api.deepseek.com", "/responses"), ("https://example.test/v1", "/v1/chat/completions")])
def test_provider_receives_strict_schema_and_response_is_decoded(monkeypatch, base, expected_path):
    plan = {"dataset": "purchase_orders", "metric": "count"}
    def respond(request):
        assert request.url.path == expected_path
        payload = json.loads(request.content)
        assert payload["temperature"] == 0.2
        if expected_path == "/responses":
            assert payload["store"] is False
            assert payload["text"]["format"]["strict"] is True
            assert payload["text"]["format"]["schema"]["additionalProperties"] is False
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(plan)}]}]})
        assert payload["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(plan)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    settings = Settings(_env_file=None, openai_base_url=base, openai_api_key="test-key", llm_max_retries=0)
    response = asyncio.run(service.chat(AIChatRequest(messages=[AIChatMessage(role="user", content="合成计划协议测试")]), settings,
        response_format=schema_response_format(text2sql.QueryPlan, "query_plan"), interpret_only=True))
    assert text2sql.QueryPlan.model_validate_json(response.message.content).dataset == "purchase_orders"


def test_truncated_structured_output_is_rejected_before_plan_validation(monkeypatch):
    def respond(request):
        return httpx.Response(200, json={"status": "incomplete", "output": []})
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(BusinessValidationError, match="无法识别"):
        asyncio.run(service.chat(AIChatRequest(messages=[AIChatMessage(role="user", content="合成问题")]),
            Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=0),
            response_format=schema_response_format(text2sql.QueryPlan, "query_plan"), interpret_only=True))
