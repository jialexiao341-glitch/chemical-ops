"""AI 服务配置与 OpenAI 兼容调用测试。"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai.schema import AIChatRequest
from app.modules.ai.llm import chat


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
    from app.modules.ai import llm, service

    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)
    settings = Settings(openai_api_key="test-key", openai_base_url="https://api.deepseek.com", llm_model="deepseek-flash")
    request = AIChatRequest(messages=[{"role": "user", "content": "查询采购订单"}])

    response = asyncio.run(chat(request, settings))

    assert response.message.content.startswith("已收到")
    assert response.model == "deepseek-flash"
    assert FakeClient.last_payload is not None
    assert FakeClient.last_payload["json"]["model"] == "deepseek-flash"
    assert FakeClient.last_payload["json"]["thinking"] == {"type": "enabled"}
    assert FakeClient.last_payload["json"].get("response_format") is None
    assert FakeClient.last_payload["json"]["messages"][0]["role"] == "system"


def test_ai_service_retries_transient_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import llm, service

    class FlakyClient(FakeClient):
        attempts = 0

        async def post(self, _url: str, *, headers: dict[str, str], json: dict) -> FakeResponse:
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise llm.httpx.ConnectError("temporary", request=None)
            return await super().post(_url, headers=headers, json=json)

    monkeypatch.setattr(llm.httpx, "AsyncClient", FlakyClient)
    monkeypatch.setattr(llm, "_retry_wait", lambda _attempt: asyncio.sleep(0))
    settings = Settings(openai_api_key="test-key", llm_max_retries=1)
    request = AIChatRequest(messages=[{"role": "user", "content": "查询库存"}])

    response = asyncio.run(chat(request, settings))

    assert response.message.content.startswith("已收到")
    assert FlakyClient.attempts == 2


def test_ai_service_does_not_retry_ambiguous_response_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import llm

    class TimedOutClient(FakeClient):
        attempts = 0

        async def post(self, _url: str, *, headers: dict[str, str], json: dict) -> FakeResponse:
            type(self).attempts += 1
            raise llm.httpx.ReadTimeout("response timed out", request=None)

    monkeypatch.setattr(llm.httpx, "AsyncClient", TimedOutClient)
    monkeypatch.setattr(llm, "_retry_wait", lambda _attempt: asyncio.sleep(0))
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=3)
    request = AIChatRequest(messages=[{"role": "user", "content": "查询库存"}])

    with pytest.raises(BusinessValidationError, match="响应超时"):
        asyncio.run(chat(request, settings))

    assert TimedOutClient.attempts == 1


def test_ai_service_treats_missing_usage_as_unavailable_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import AsyncClient, MockTransport, Response
    from app.modules.ai import llm

    def respond(_request):
        return Response(200, json={"choices": [{"message": {"content": "回答"}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient",
                        lambda **kwargs: AsyncClient(transport=MockTransport(respond), **kwargs))
    result = asyncio.run(chat(
        AIChatRequest(messages=[{"role": "user", "content": "只读 usage 口径测试"}]),
        Settings(_env_file=None, openai_api_key="test-key", llm_max_retries=0), interpret_only=True))
    assert result.message.content == "回答"
    assert result.usage is None


def test_ai_attachment_is_rescanned_before_ai_use(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.modules.ai import llm, service
    from app.modules.files.scanner import FileScanResult

    uploaded_file = SimpleNamespace(id=12, uploader_id=1, file_name="库存.csv", mime_type="text/csv")
    monkeypatch.setattr(service, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(service.file_service, "get_file", lambda *_args: uploaded_file)
    monkeypatch.setattr(service.file_service, "read_file", lambda *_args: (uploaded_file, "物料,数量\n乙醇,12".encode("utf-8")))
    monkeypatch.setattr(service, "scan_content", lambda *_args, **_kwargs: FileScanResult(status="UNAVAILABLE", detail="clamdscan 不可用"))

    context, images, citations = asyncio.run(service._prepare_attachments(
        SimpleNamespace(),
        SimpleNamespace(id=1),
        AIChatRequest(messages=[{"role": "user", "content": "分析附件"}], attachment_file_ids=[12]),
        Settings(file_scan_enabled=True),
    ))

    assert context == []
    assert images == []
    assert citations[0]["parse_status"] == "SCAN_BLOCKED"


def test_ai_service_rejects_missing_api_key() -> None:
    settings = Settings(openai_api_key="")
    request = AIChatRequest(messages=[{"role": "user", "content": "查询库存"}])

    with pytest.raises(BusinessValidationError, match="API key"):
        asyncio.run(chat(request, settings))


def test_cancelled_chat_releases_database_connection_during_model_wait(db_engine, monkeypatch) -> None:
    """A stalled route/model call must not retain a pooled SQL connection."""
    from app.modules.ai import conversation_store, routing, service
    from app.modules.ai.schema import AIChatMessage
    from app.modules.system.model import User

    question = f"事务边界取消验收 {uuid4().hex}"
    db = Session(bind=db_engine, autoflush=False, expire_on_commit=False)
    conversation_id = None

    async def run() -> None:
        nonlocal conversation_id
        user = db.scalar(select(User).where(User.username == "buyer"))
        assert user is not None
        initial = AIChatRequest(messages=[AIChatMessage(role="user", content=question)])
        conversation = conversation_store.ensure_conversation(db, user, initial)
        conversation_id = conversation.id
        db.commit()
        baseline = db_engine.pool.checkedout()
        entered = asyncio.Event()

        async def stalled(*_args, **_kwargs):
            assert db_engine.pool.checkedout() == baseline
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(routing, "understand", stalled)
        task = asyncio.create_task(service._chat_for_user_impl(
            db, user, AIChatRequest(conversation_id=conversation_id,
                messages=[AIChatMessage(role="user", content=question)])))
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert db_engine.pool.checkedout() == baseline
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert db_engine.pool.checkedout() == baseline
        assert not db.in_transaction()

    try:
        asyncio.run(run())
    finally:
        db.rollback()
        if conversation_id is not None:
            user = db.scalar(select(User).where(User.username == "buyer"))
            if user is not None:
                conversation_store.delete_conversation(db, user, conversation_id)
        db.close()


def test_ai_message_context_marks_only_verified_attachment_content() -> None:
    from app.modules.ai.llm import _build_messages

    request = AIChatRequest(
        messages=[{"role": "user", "content": "请读取这个报价单"}],
        attachments=["quote.csv"],
        attachment_file_ids=[12],
    )

    messages = _build_messages(request, ["附件：quote.csv\n供应商,单价\n甲公司,12.5"])

    assert messages[-1]["role"] == "system"
    assert "甲公司,12.5" in messages[-1]["content"]
    assert "尚未读取" not in messages[-1]["content"]


def test_native_image_payload_skips_document_parser() -> None:
    from app.modules.ai.llm import _build_messages
    from app.modules.ai.service import _build_native_image_part

    request = AIChatRequest(messages=[{"role": "user", "content": "请读取图片中的批次号"}], attachments=["label.png"], attachment_file_ids=[12])
    image_part = _build_native_image_part("label.png", "image/png", b"png-bytes")

    assert image_part is not None
    messages = _build_messages(request, image_parts=[image_part])
    content = messages[-1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "请读取图片中的批次号"}
    assert content[1]["type"] == "image_url"
    assert "data:image/png;base64," in content[1]["image_url"]["url"]


def test_ai_business_context_is_not_built_for_queries() -> None:
    from app.modules.ai import llm, service

    assert not hasattr(service, "_build_business_context")


def test_overdue_delivery_query_has_safe_plan_fallback() -> None:
    from app.modules.ai.text2sql import _fallback_query_plan

    plan = _fallback_query_plan("查看本周逾期到货")
    assert plan is not None
    assert plan.dataset == "deliveries"
    assert plan.metric == "count"
    from datetime import date, timedelta

    assert plan.time_field == "expected_arrival_date"
    assert plan.date_from == date.today() - timedelta(days=date.today().weekday())
    assert plan.date_to == date.today() - timedelta(days=1)
    assert plan.filters[0].field == "status"
    assert plan.filters[0].value == "IN_TRANSIT"
    assert plan.group_by == "supplier"


def test_stream_text_chunks_are_incremental() -> None:
    from app.modules.ai.service import _stream_text_chunks, STREAM_CHUNK_SIZE
    content = "你好，我是化运助手。" * 20

    async def collect() -> list[str]:
        return [chunk async for chunk in _stream_text_chunks(content)]

    chunks = asyncio.run(collect())
    assert len(chunks) > 1
    assert "".join(chunks) == content
    assert all(0 < len(chunk) <= STREAM_CHUNK_SIZE for chunk in chunks)


def test_ai_chat_routes_business_query_to_text2sql(client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import llm, service

    from app.modules.ai import routing
    async def understand(*args, **kwargs):
        return routing.Understanding(purpose='query', tasks=['analytics'])
    monkeypatch.setattr(routing, 'understand', understand)

    calls: list[str] = []

    from app.modules.ai.schema import AIQueryTrace

    async def fake_text2sql(*args: object, **_kwargs: object) -> tuple[str, dict[str, object], AIQueryTrace]:
        calls.append(str(args[2]))
        trace = AIQueryTrace(query=str(args[2]), slots=[], template="采购订单 · SUM(order_amount)", sql="SELECT ...", columns=[{"key": "supplier", "label": "供应商", "format": "text"}, {"key": "metric_value", "label": "指标值", "format": "amount"}], rows=[{"supplier": "甲公司", "metric_value": "100"}], row_count=1, truncated=False, stages=["execution"], render={"type": "table", "title": "采购订单查询结果", "empty_text": "没有符合条件的数据", "columns": [{"key": "supplier", "label": "供应商", "format": "text"}, {"key": "metric_value", "label": "指标值", "format": "amount"}]})
        return "查询已通过 Text2SQL 执行，共返回 1 条结果：\n1. 供应商：甲公司；指标值：100", {"type": "text2sql", "source": "实时数据库只读查询", "row_count": 1, "stages": ["execution"], "query_trace": trace.model_dump(mode="json")}, trace

    monkeypatch.setattr(service, "_run_text2sql_for_chat", fake_text2sql)
    response = client.post(
        "/api/v1/ai/chat",
        headers=_login(client, demo_password),
        json={"messages": [{"role": "user", "content": "查询本月各供应商采购订单总金额"}]},
    )

    assert response.status_code == 200, response.text
    assert calls == ["查询本月各供应商采购订单总金额"]
    assert response.json()["model"] == "text2sql"
    assert response.json()["citations"][0]["type"] == "text2sql"
    assert response.json()["user_query"] == "查询本月各供应商采购订单总金额"
    assert response.json()["answer"].startswith("查询已通过")
    assert response.json()["query_trace"]["rows"][0]["supplier"] == "甲公司"
    assert "dashboard_overview" not in response.text
    assert "recent_purchase_orders" not in response.text


def test_ai_conversation_list_requires_login_and_reads_database(client: TestClient, demo_password: str) -> None:
    unauthorized = client.get("/api/v1/ai/conversations")
    assert unauthorized.status_code == 401

    response = client.get("/api/v1/ai/conversations", headers=_login(client, demo_password))
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"items", "total"}


def test_ai_chat_persists_conversation_and_messages(client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import routing, service
    from app.modules.ai.schema import AIQueryTrace

    async def fake_text2sql(*args: object, **_kwargs: object) -> tuple[str, dict[str, object], AIQueryTrace]:
        assert args[2] == "查询采购订单"
        trace = AIQueryTrace(query=str(args[2]), slots=[], template="采购订单 · COUNT", sql="SELECT ...", columns=[{"key": "metric_value", "label": "指标值", "format": "text"}], rows=[], row_count=0, truncated=False, stages=["execution"], render={"type": "table", "title": "采购订单查询结果", "empty_text": "没有符合条件的数据", "columns": [{"key": "metric_value", "label": "指标值", "format": "text"}]})
        return "查询已通过 Text2SQL 执行，但没有找到符合条件的数据。", {"type": "text2sql", "source": "实时数据库只读查询", "row_count": 0, "stages": ["execution"], "query_trace": trace.model_dump(mode="json")}, trace

    async def understand(*args, **kwargs):
        return routing.Understanding(purpose="query", tasks=["analytics"], sub_tasks=[
            routing.SubTask(id="t1", kind="analytics", question="查询采购订单")])
    monkeypatch.setattr(routing, "understand", understand)
    monkeypatch.setattr(service, "_run_text2sql_for_chat", fake_text2sql)
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

    from app.modules.ai import llm, service
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
    from app.modules.ai import llm, service
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
