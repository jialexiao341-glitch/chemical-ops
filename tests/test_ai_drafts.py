"""AI 采购草稿建议必须先校验，且本服务只生成预览。"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.errors import BusinessValidationError
from app.modules.ai import drafts


def _run_immediate(coroutine):
    """运行不含实际 I/O 的异步服务，避免测试依赖 Windows 事件循环初始化。"""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("测试替身不应挂起等待")


def test_preview_endpoint_is_available_to_authorized_user_without_creating_a_request(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ai import controller
    from app.modules.ai.schema import AIPurchaseDraftPreview

    async def fake_proposal(*_args, **_kwargs):
        return AIPurchaseDraftPreview(
            draft={"purpose": "实验", "items": [{"requested_name": "乙醇", "quantity": "12", "unit_id": 3}]},
            display_items=[{"requested_name": "乙醇", "quantity": "12", "unit_name": "升"}],
            warnings=[],
        )

    monkeypatch.setattr(controller.drafts_service, "propose_purchase_request_draft", fake_proposal)
    token_response = client.post(
        "/api/v1/auth/login",
        json={"username": "system_admin", "password": demo_password},
    )
    assert token_response.status_code == 200, token_response.text
    response = client.post(
        "/api/v1/ai/purchase-request-draft/preview",
        headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
        json={"question": "采购乙醇 12 升，用于实验"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["requires_user_confirmation"] is True
    assert response.json()["draft"]["purpose"] == "实验"


class _Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Database:
    def __init__(self):
        self.results = [
            _Rows([SimpleNamespace(id=3, unit_name="升", dimension="VOLUME", status="ACTIVE")]),
        ]

    def scalars(self, _query):
        return self.results.pop(0)


def test_proposal_uses_authorized_tools_and_persists_versioned_confirmation(monkeypatch) -> None:
    from app.modules.ai import conversation_store
    monkeypatch.setattr(conversation_store, 'get_owned_conversation', lambda *_args: object())
    async def fake_chat(request, _settings, *, attachment_context, response_format):
        assert "请按提供的规则整理字段" in request.messages[0].content
        assert "采购乙醇 12 升，用于实验" in attachment_context[0]
        assert response_format["type"] == "json_schema"
        return SimpleNamespace(
            answer=json.dumps(
                {
                    "purpose": "实验",
                    "priority": "NORMAL",
                    "currency_code": "CNY",
                    "items": [{"requested_name": "乙醇", "product_id": 9, "quantity": "12", "unit_id": 3}],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(drafts, "get_user_permission_codes", lambda *_args: ["procurement.requests.write", "master.products.read", "warehouse.inventory.read", "procurement.rfqs.read"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(drafts, "chat", fake_chat)
    from app.modules.ai import action_proposals
    from datetime import datetime, timezone
    proposed_actions = []
    def fake_propose(_db, _user, action_type, payload, *, idempotency_key):
        proposed_actions.append((action_type, payload, idempotency_key))
        return SimpleNamespace(confirmation_id="f" * 32, preview_version=1,
                               expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(action_proposals, "propose_action", fake_propose)
    from types import SimpleNamespace
    database = _Database()
    product = SimpleNamespace(id=9, product_name="乙醇", status="ACTIVE", version_no=3, unit_id=3)
    database.get = lambda _model, _id: product
    database.added = []
    database.add = database.added.append
    database.commit = lambda: None
    database.execute = lambda _query: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    def fake_tool(_db, _user, call):
        if call.tool == "catalog.search_products":
            return SimpleNamespace(tool=call.tool, rows=[SimpleNamespace(product_id=9, model_dump=lambda **_kwargs: {"product_id": 9})], total_rows=1, truncated=False, sources=[])
        if call.tool == "inventory.query_available":
            return SimpleNamespace(tool=call.tool, scope="授权仓库", observed_at=datetime.now(timezone.utc), totals=[], sources=[])
        return SimpleNamespace(tool=call.tool, rows=[], total_rows=0, truncated=False, sources=[])
    monkeypatch.setattr(drafts.agent_tools, "execute_tool", fake_tool)

    preview = _run_immediate(
        drafts.propose_purchase_request_draft(
            database,
            SimpleNamespace(id=5, department_id=2, status="ACTIVE"),
            "采购乙醇 12 升，用于实验",
            conversation_id=77,
        )
    )

    assert preview.requires_user_confirmation is True
    assert preview.draft["department_id"] == 2
    assert "status" not in preview.draft
    assert preview.draft["items"][0]["product_id"] == 9
    assert preview.display_items[0].quantity == "12"
    assert preview.display_items[0].unit_name == "升"
    assert preview.confirmation_id and preview.preview_version == 1
    assert proposed_actions[0][0] == "purchase_request.create_draft"
    assert proposed_actions[0][1]["items"][0]["product_id"] == 9
    assert proposed_actions[0][2]
    assert database.added == []
    assert {"type": "conversation", "conversation_id": 77} in preview.evidence


def test_proposal_returns_clarification_without_issuing_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(drafts, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])

    async def missing_chat(*_args, **_kwargs):
        return SimpleNamespace(answer=json.dumps({"purpose": "", "items": [{"requested_name": "乙醇"}], "missing_fields": ["数量", "单位"]}))

    monkeypatch.setattr(drafts, "chat", missing_chat)
    preview = _run_immediate(drafts.propose_purchase_request_draft(
        _Database(), SimpleNamespace(id=5, department_id=2, status="ACTIVE"), "帮我整理一份采购申请"
    ))
    assert "采购用途" in preview.missing_fields
    assert "数量" in preview.missing_fields
    assert not preview.confirmation_id
