"""AI 服务配置与 OpenAI 兼容调用测试。"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai.schema import AIChatRequest
from app.modules.ai.service import chat


def _login(client: TestClient, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": "system_admin", "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"role": "assistant", "content": "已收到，我会基于真实业务数据分析。"}}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}}


class FakeClient:
    last_payload: dict | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, _url: str, *, headers: dict[str, str], json: dict) -> FakeResponse:
        FakeClient.last_payload = {"headers": headers, "json": json}
        return FakeResponse()


def test_ai_service_uses_deepseek_model_without_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import service

    monkeypatch.setattr(service.httpx, "AsyncClient", FakeClient)
    settings = Settings(openai_api_key="test-key", openai_base_url="https://api.deepseek.com", llm_model="deepseek-flash")
    request = AIChatRequest(messages=[{"role": "user", "content": "查询采购订单"}])

    response = asyncio.run(chat(request, settings))

    assert response.message.content.startswith("已收到")
    assert response.model == "deepseek-flash"
    assert FakeClient.last_payload is not None
    assert FakeClient.last_payload["json"]["model"] == "deepseek-flash"
    assert FakeClient.last_payload["json"]["messages"][0]["role"] == "system"


def test_ai_service_rejects_missing_api_key() -> None:
    settings = Settings(openai_api_key="")
    request = AIChatRequest(messages=[{"role": "user", "content": "查询库存"}])

    with pytest.raises(BusinessValidationError, match="API key"):
        asyncio.run(chat(request, settings))


def test_ai_message_context_marks_only_verified_attachment_content() -> None:
    from app.modules.ai.service import _build_messages

    request = AIChatRequest(
        messages=[{"role": "user", "content": "请读取这个报价单"}],
        attachments=["quote.csv"],
        attachment_file_ids=[12],
    )

    messages = _build_messages(request, ["附件：quote.csv\n供应商,单价\n甲公司,12.5"])

    assert messages[-1]["role"] == "system"
    assert "甲公司,12.5" in messages[-1]["content"]
    assert "尚未读取" not in messages[-1]["content"]


def test_ai_business_context_uses_real_dashboard_and_detail_queries(db_session) -> None:
    from app.modules.ai.service import _build_business_context
    from app.modules.ai.schema import AIChatRequest
    from app.modules.system.crud import get_user_by_username

    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    context, citations = _build_business_context(db_session, user, AIChatRequest(messages=[{"role": "user", "content": "查询库存和采购订单"}]))

    assert context
    assert "dashboard_overview" in context[0]
    assert citations[0]["type"] == "business_context"


def test_ai_business_context_includes_quality_exception_finance_and_supplier_data(db_session) -> None:
    """系统管理员查询其他业务域时，AI 上下文来自真实只读表且不包含写操作。"""

    import json

    from app.modules.ai.service import _build_business_context
    from app.modules.system.crud import get_user_by_username

    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    context, citations = _build_business_context(
        db_session,
        user,
        AIChatRequest(messages=[{"role": "user", "content": "查询质量验收、异常、财务和供应商"}]),
    )

    assert context
    payload = json.loads(context[0].split("\n", 1)[1])
    assert "quality_acceptances" in payload
    assert "operation_exceptions" in payload
    assert "finance_reconciliations" in payload
    assert "suppliers" in payload
    assert {"quality_acceptances", "operation_exceptions", "finance_reconciliations", "suppliers"}.issubset(set(citations[0]["sections"]))


def test_ai_conversation_list_requires_login_and_reads_database(client: TestClient, demo_password: str) -> None:
    unauthorized = client.get("/api/v1/ai/conversations")
    assert unauthorized.status_code == 401

    response = client.get("/api/v1/ai/conversations", headers=_login(client, demo_password))
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"items", "total"}


def test_ai_chat_persists_conversation_and_messages(client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import service
    from app.modules.ai.schema import AIChatResponse, AIChatMessage

    async def fake_chat(*_args: object, **_kwargs: object) -> AIChatResponse:
        return AIChatResponse(
            message=AIChatMessage(role="assistant", content="已基于当前业务数据完成分析。"),
            conversation_id=0,
            model="deepseek-flash",
            provider="openai_compatible",
        )

    monkeypatch.setattr(service, "chat", fake_chat)
    headers = _login(client, demo_password)
    response = client.post("/api/v1/ai/chat", headers=headers, json={"messages": [{"role": "user", "content": "查询采购订单"}]})

    assert response.status_code == 200, response.text
    conversation_id = response.json()["conversation_id"]
    assert conversation_id > 0
    history = client.get(f"/api/v1/ai/conversations/{conversation_id}/messages", headers=headers)
    assert history.status_code == 200, history.text
    assert [item["role"] for item in history.json()["items"]] == ["user", "assistant"]


def test_ai_chat_persists_attachment_parse_citation(client: TestClient, db_session, demo_password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.modules.ai import service
    from app.modules.ai.schema import AIChatMessage, AIChatResponse
    from app.modules.system.crud import get_user_by_username

    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    uploaded_file = SimpleNamespace(id=77, uploader_id=user.id, file_name="库存.csv", mime_type="text/csv")

    async def fake_chat(*_args: object, **kwargs: object) -> AIChatResponse:
        context = kwargs.get("attachment_context") or []
        assert any("乙醇" in item for item in context)
        return AIChatResponse(message=AIChatMessage(role="assistant", content="已读取附件。"), conversation_id=0, model="deepseek-flash", provider="openai_compatible")

    monkeypatch.setattr(service.file_service, "get_file", lambda *_args: uploaded_file)
    monkeypatch.setattr(service.file_service, "read_file", lambda *_args: (uploaded_file, "物料,数量\n乙醇,12".encode()))
    monkeypatch.setattr(service, "chat", fake_chat)
    headers = _login(client, demo_password)
    response = client.post("/api/v1/ai/chat", headers=headers, json={"messages": [{"role": "user", "content": "分析库存附件"}], "attachments": ["库存.csv"], "attachment_file_ids": [77]})

    assert response.status_code == 200, response.text
    history = client.get(f"/api/v1/ai/conversations/{response.json()['conversation_id']}/messages", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["citations"][0]["parse_status"] == "SUCCEEDED"
    assert uploaded_file.parse_status == "SUCCEEDED"


def test_ai_chat_uses_mineru_for_enabled_office_attachment(client: TestClient, db_session, demo_password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """启用 MinerU 时，AI 附件链路使用远程解析结果并保存解析器引用。"""

    from types import SimpleNamespace

    from app.core.config import Settings
    from app.modules.ai import service
    from app.modules.ai.schema import AIChatMessage, AIChatResponse
    from app.modules.files.parser import ParsedFile
    from app.modules.system.crud import get_user_by_username

    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    uploaded_file = SimpleNamespace(id=78, uploader_id=user.id, file_name="到货计划.pdf", mime_type="application/pdf")
    calls: list[tuple[str, Settings]] = []

    def fake_mineru(file_name: str, _content: bytes, settings: Settings) -> ParsedFile:
        calls.append((file_name, settings))
        assert uploaded_file.parse_status == "PROCESSING"
        return ParsedFile(
            status="SUCCEEDED",
            text="# 到货计划\n\n乙醇：12 千克",
            parser="mineru-v4-vlm",
            references=[{"type": "mineru", "locator": "full.md", "batch_id": "batch-test"}],
        )

    async def fake_chat(*_args: object, **kwargs: object) -> AIChatResponse:
        assert any("乙醇：12 千克" in item for item in (kwargs.get("attachment_context") or []))
        return AIChatResponse(message=AIChatMessage(role="assistant", content="已读取 MinerU 解析结果。"), conversation_id=0, model="deepseek-flash", provider="openai_compatible")

    monkeypatch.setattr(service.file_service, "get_file", lambda *_args: uploaded_file)
    monkeypatch.setattr(service.file_service, "read_file", lambda *_args: (uploaded_file, b"%PDF-test"))
    monkeypatch.setattr(service.mineru, "parse_bytes", fake_mineru)
    monkeypatch.setattr(service, "get_settings", lambda: Settings(openai_api_key="test-key", mineru_enabled=True))
    monkeypatch.setattr(service, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/chat",
        headers=_login(client, demo_password),
        json={"messages": [{"role": "user", "content": "分析这个附件"}], "attachments": ["到货计划.pdf"], "attachment_file_ids": [78]},
    )

    assert response.status_code == 200, response.text
    assert calls and calls[0][0] == "到货计划.pdf"
    assert calls[0][1].mineru_enabled is True
    history = client.get(f"/api/v1/ai/conversations/{response.json()['conversation_id']}/messages", headers=_login(client, demo_password))
    assert history.status_code == 200, history.text
    citation = history.json()["items"][0]["citations"][0]
    assert citation["parser"] == "mineru-v4-vlm"
    assert citation["references"][0]["locator"] == "full.md"
