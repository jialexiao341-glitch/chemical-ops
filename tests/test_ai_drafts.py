"""AI 采购草稿建议必须先校验，且本服务只生成预览。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.errors import BusinessValidationError
from app.modules.ai import drafts


def test_preview_endpoint_is_available_to_authorized_user_without_creating_a_request(
    client: TestClient, demo_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.ai import controller
    from app.modules.ai.schema import AIPurchaseDraftPreview

    async def fake_proposal(*_args):
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
            _Rows([SimpleNamespace(id=9, product_name="乙醇", status="ACTIVE")]),
            _Rows([SimpleNamespace(id=3, unit_name="升", dimension="VOLUME", status="ACTIVE")]),
        ]

    def scalars(self, _query):
        return self.results.pop(0)


def test_proposal_uses_only_valid_active_catalog_ids_and_does_not_write(monkeypatch) -> None:
    async def fake_chat(request, _settings, *, attachment_context, response_format):
        assert "请按提供的规则整理字段" in request.messages[0].content
        assert "采购乙醇 12 升，用于实验" in attachment_context[0]
        assert response_format == {"type": "json_object"}
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

    monkeypatch.setattr(drafts, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(drafts, "chat", fake_chat)

    preview = asyncio.run(
        drafts.propose_purchase_request_draft(
            _Database(),
            SimpleNamespace(id=5, department_id=2),
            "采购乙醇 12 升，用于实验",
        )
    )

    assert preview.requires_user_confirmation is True
    assert preview.draft["department_id"] == 2
    assert "status" not in preview.draft
    assert preview.draft["items"][0]["product_id"] == 9
    assert preview.display_items[0].quantity == "12"
    assert preview.display_items[0].unit_name == "升"


def test_proposal_rejects_missing_fields_and_invalid_catalog_ids(monkeypatch) -> None:
    monkeypatch.setattr(drafts, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])

    async def missing_chat(*_args, **_kwargs):
        return SimpleNamespace(answer=json.dumps({"purpose": "", "items": [{"requested_name": "乙醇"}], "missing_fields": ["数量", "单位"]}))

    monkeypatch.setattr(drafts, "chat", missing_chat)
    with pytest.raises(BusinessValidationError, match="数量、单位"):
        asyncio.run(
            drafts.propose_purchase_request_draft(
                _Database(), SimpleNamespace(id=5, department_id=2), "帮我整理一份采购申请"
            )
        )

    async def invalid_catalog_chat(*_args, **_kwargs):
        return SimpleNamespace(answer=json.dumps({"purpose": "实验", "items": [{"requested_name": "乙醇", "quantity": "12", "unit_id": 999}]}))

    monkeypatch.setattr(drafts, "chat", invalid_catalog_chat)
    with pytest.raises(BusinessValidationError, match="计量单位"):
        asyncio.run(
            drafts.propose_purchase_request_draft(
                _Database(), SimpleNamespace(id=5, department_id=2), "采购乙醇 12 升"
            )
        )
