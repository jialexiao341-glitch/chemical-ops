"""AI 运营晨报（/ai/briefing）与自然语言筛选解析（/ai/parse-filters）测试。"""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.errors import BusinessValidationError
from app.modules.ai import briefing, nl_filters
from app.modules.ai.catalog import CATALOG
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatResponse,
    BriefingRequest,
    NLFilterRequest,
)


def _fake_chat_response(content: str) -> AIChatResponse:
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=0,
        model="deepseek-flash",
        provider="openai_compatible",
        answer=content,
    )


def _login(client: TestClient, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system_admin", "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------- 纯函数：白名单校验 ----------


def test_resolve_dataset_rejects_unknown_key():
    with pytest.raises(BusinessValidationError, match="不支持的数据集"):
        nl_filters.resolve_dataset("sys_users")

    spec = nl_filters.resolve_dataset("purchase_orders")
    assert spec.label == "采购订单"


def test_validate_filter_payload_whitelists_fields_and_values():
    spec = CATALOG["purchase_requests"]
    payload = {
        "filters": {"status": "审批中", "priority": "紧急", "password_hash": "x"},
        "time_range": {"field": "created_at", "date_from": "2026-09-01", "date_to": "2026-09-22"},
        "keywords": " 乙醇 ",
    }

    filters, time_range, keywords, dropped = nl_filters.validate_filter_payload(
        payload, spec, "purchase_requests"
    )

    # 中文标签归一为规范枚举值
    assert filters == {"status": "APPROVING", "priority": "URGENT"}
    assert time_range is not None
    assert time_range.field == "created_at"
    assert time_range.date_from == date(2026, 9, 1)
    assert time_range.date_to == date(2026, 9, 22)
    assert keywords == "乙醇"
    assert any("password_hash" in item for item in dropped)


def test_validate_filter_payload_drops_bad_enum_list_and_time_field():
    spec = CATALOG["deliveries"]
    payload = {
        "filters": {"status": "已起飞", "supplier_name": ["甲", "乙"]},
        "time_range": {"field": "created_at", "date_from": "2026-09-01", "date_to": None},
    }

    filters, time_range, _keywords, dropped = nl_filters.validate_filter_payload(
        payload, spec, "deliveries"
    )

    # 非法枚举与列表值被剔除；created_at 在白名单内，单侧时间范围照常通过
    assert filters == {}
    assert time_range is not None
    assert time_range.field == "created_at"
    assert time_range.date_from == date(2026, 9, 1)
    assert time_range.date_to is None
    assert any("已起飞" in item for item in dropped)
    assert any("supplier_name" in item for item in dropped)


def test_validate_filter_payload_time_range_requires_whitelisted_field():
    spec = CATALOG["deliveries"]
    payload = {
        "filters": {},
        "time_range": {"field": "password", "date_from": "2026-09-01", "date_to": None},
    }

    _filters, time_range, _keywords, dropped = nl_filters.validate_filter_payload(
        payload, spec, "deliveries"
    )

    assert time_range is None
    assert any("time_range.field" in item for item in dropped)


def test_validate_filter_payload_rejects_inverted_date_range():
    spec = CATALOG["purchase_orders"]
    payload = {
        "filters": {},
        "time_range": {
            "field": "order_date",
            "date_from": "2026-09-20",
            "date_to": "2026-09-01",
        },
    }

    _filters, time_range, _keywords, dropped = nl_filters.validate_filter_payload(
        payload, spec, "purchase_orders"
    )

    assert time_range is None
    assert any("开始日期晚于结束日期" in item for item in dropped)


def test_validate_filter_payload_truncates_keywords():
    spec = CATALOG["suppliers"]
    payload = {"filters": {}, "time_range": None, "keywords": "长" * 500}

    _filters, _time_range, keywords, _dropped = nl_filters.validate_filter_payload(
        payload, spec, "suppliers"
    )

    assert keywords is not None
    assert len(keywords) == nl_filters.MAX_KEYWORDS_LENGTH


def test_build_filter_prompt_contains_whitelist_and_date():
    spec = CATALOG["exceptions"]
    prompt = nl_filters.build_filter_prompt(
        "exceptions", spec, "查一下处理中的高严重度异常", today=date(2026, 9, 22)
    )

    assert "今天是 2026-09-22" in prompt
    assert "运营异常" in prompt
    assert "severity" in prompt
    assert "处理中=PROCESSING" in prompt
    assert "查一下处理中的高严重度异常" in prompt
    assert "password" not in prompt or "password_hash" not in prompt


def test_require_dataset_access_denies_without_permission(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nl_filters, "get_user_role_codes", lambda *_args: ["WAREHOUSE"])
    monkeypatch.setattr(
        nl_filters, "get_user_permission_codes", lambda *_args: ["warehouse.inventory.read"]
    )

    with pytest.raises(BusinessValidationError, match="权限"):
        nl_filters.require_dataset_access(
            object(), SimpleNamespace(id=1), CATALOG["purchase_orders"]
        )

    # 有对应权限码时放行
    monkeypatch.setattr(
        nl_filters, "get_user_permission_codes", lambda *_args: ["procurement.orders.read"]
    )
    nl_filters.require_dataset_access(
        object(), SimpleNamespace(id=1), CATALOG["purchase_orders"]
    )


# ---------- 纯函数：晨报提示词 ----------


def test_briefing_prompt_requires_three_sections_and_no_fabrication():
    snapshot = {"date": "2026-09-22", "overview": {"open_exceptions": 3}}
    prompt = briefing.build_prompt(snapshot)

    assert "【概览】" in prompt
    assert "【需关注】" in prompt
    assert "【建议】" in prompt
    assert "禁止编造" in prompt
    assert '"open_exceptions": 3' in prompt


def test_json_safe_converts_decimal_and_dates():
    from decimal import Decimal

    payload = {
        "amount": Decimal("12.50"),
        "day": date(2026, 9, 22),
        "nested": [{"qty": Decimal("1.00")}],
    }

    safe = briefing.json_safe(payload)

    assert safe["amount"] == "12.50"
    assert safe["day"] == "2026-09-22"
    assert safe["nested"][0]["qty"] == "1.00"
    # 结果必须能被 json 序列化（晨报快照要进响应体）
    json.dumps(safe)


# ---------- 接口：晨报 ----------


def test_briefing_requires_login(client: TestClient):
    response = client.post("/api/v1/ai/briefing", json={})
    assert response.status_code == 401


def test_briefing_generates_content_without_push(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
):
    captured: dict = {}

    async def fake_chat(*_args, **kwargs):
        captured["request"] = _args[0] if _args else None
        return _fake_chat_response("【概览】今日订单 10 单。【需关注】无异常。【建议】保持。")

    monkeypatch.setattr(briefing, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/briefing",
        headers=_login(client, demo_password),
        json={"push": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"].startswith("【概览】")
    assert body["pushed"] is False
    assert body["notified_count"] == 0
    assert "overview" in body["snapshot"]
    assert body["snapshot"]["date"] == date.today().isoformat()
    # 提示词确实带上了快照
    assert captured["request"] is not None
    assert "数据快照" in captured["request"].messages[0].content


def test_briefing_push_notifies_default_roles(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
):
    async def fake_chat(*_args, **_kwargs):
        return _fake_chat_response("【概览】推送测试。【需关注】无。【建议】无。")

    monkeypatch.setattr(briefing, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/briefing",
        headers=_login(client, demo_password),
        json={"push": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pushed"] is True
    # 开发库至少有 system_admin 属于默认通知角色
    assert body["notified_count"] >= 1


# ---------- 接口：自然语言筛选 ----------


def test_parse_filters_requires_login(client: TestClient):
    response = client.post(
        "/api/v1/ai/parse-filters",
        json={"dataset": "purchase_orders", "question": "审批中的订单"},
    )
    assert response.status_code == 401


def test_parse_filters_returns_whitelisted_params(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
):
    model_output = json.dumps(
        {
            "filters": {"status": "审批中"},
            "time_range": {
                "field": "order_date",
                "date_from": "2026-09-01",
                "date_to": "2026-09-22",
            },
            "keywords": None,
        },
        ensure_ascii=False,
    )

    async def fake_chat(*_args, **kwargs):
        assert kwargs.get("response_format") == {"type": "json_object"}
        return _fake_chat_response(model_output)

    monkeypatch.setattr(nl_filters, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/parse-filters",
        headers=_login(client, demo_password),
        json={
            "dataset": "purchase_orders",
            "question": "本月审批中的采购订单",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset_label"] == "采购订单"
    assert body["filters"] == {"status": "APPROVING"}
    assert body["time_range"]["field"] == "order_date"
    assert body["time_range"]["date_from"] == "2026-09-01"
    assert body["dropped"] == []


def test_parse_filters_rejects_unknown_dataset(client: TestClient, demo_password: str):
    response = client.post(
        "/api/v1/ai/parse-filters",
        headers=_login(client, demo_password),
        json={"dataset": "sys_users", "question": "管理员账号"},
    )

    assert response.status_code == 400, response.text
    assert "不支持的数据集" in response.json()["detail"]


def test_parse_filters_errors_when_nothing_usable(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
):
    async def fake_chat(*_args, **_kwargs):
        # 模型只给出了白名单外的字段，全部会被丢弃
        return _fake_chat_response(
            json.dumps({"filters": {"password_hash": "x"}, "time_range": None, "keywords": None})
        )

    monkeypatch.setattr(nl_filters, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/parse-filters",
        headers=_login(client, demo_password),
        json={"dataset": "purchase_orders", "question": "查点东西"},
    )

    assert response.status_code == 400, response.text
    assert "未能从描述中解析出" in response.json()["detail"]
