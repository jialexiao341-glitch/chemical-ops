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
    from app.modules.ai import conversation_store, purchase_draft_bridge as bridge_module
    monkeypatch.setattr(conversation_store, 'get_owned_conversation', lambda *_args: object())
    monkeypatch.setattr(conversation_store, 'load_purchase_draft_bridge', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge_module, 'resolve_draft_source',
                        lambda *_args, **_kwargs: bridge_module.SourceResolution(reason="NO_SOURCE"))
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
                    "items": [{"requested_name": "乙醇", "product_id": None, "quantity": "12", "unit_id": 3}],
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
    def fake_propose(_db, _user, action_type, payload, *, idempotency_key, evidence=None):
        proposed_actions.append((action_type, payload, idempotency_key, evidence))
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
    def _result(payload):
        return SimpleNamespace(model_dump=lambda **_kwargs: payload, **payload)
    def fake_tool(_db, _user, call):
        if call.tool == "catalog.search_products":
            return _result({"tool": call.tool, "rows": [SimpleNamespace(product_id=9)],
                            "total_rows": 1, "truncated": False, "sources": []})
        if call.tool == "inventory.query_available":
            return _result({"tool": call.tool, "scope": "授权仓库", "observed_at": datetime.now(timezone.utc).isoformat(),
                            "totals": [], "rows": [], "sources": [], "total_rows": 0, "truncated": False})
        if call.tool == "supplier_quotes.find_rfq_items":
            return _result({"tool": call.tool, "rows": [], "total_rows": 0, "truncated": False, "sources": []})
        return _result({"tool": call.tool, "rows": [], "total_rows": 0, "truncated": False, "sources": []})
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
    assert proposed_actions[0][3] == preview.evidence
    assert database.added == []
    tool_entries = [entry for entry in preview.evidence if entry.get("type") == "tool"]
    assert tool_entries and all(entry.get("fingerprint") and "arguments" in entry for entry in tool_entries)
    assert not any(entry.get("type") == "conversation" for entry in preview.evidence)


def _source_database():
    database = _Database()
    product = SimpleNamespace(id=9, product_name="乙醇", status="ACTIVE", version_no=3, unit_id=3)
    database.get = lambda _model, _id: product
    database.added = []
    database.add = database.added.append
    database.commit = lambda: None
    database.execute = lambda _query: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    return database


def _patch_draft_source(monkeypatch, *, source=None, saved=None, cleared=None, facts=None):
    from app.modules.ai import conversation_store, purchase_draft_bridge as bridge_module

    monkeypatch.setattr(conversation_store, "get_owned_conversation", lambda *_args: object())
    monkeypatch.setattr(conversation_store, "load_purchase_draft_bridge",
                        lambda *_args, **_kwargs: bridge)
    monkeypatch.setattr(bridge_module, "resolve_draft_source",
                        lambda *_args, **_kwargs: bridge_module.SourceResolution(source=source) if source
                        else bridge_module.SourceResolution(reason="NO_SOURCE"))
    monkeypatch.setattr(bridge_module, "restore_bridge_source", lambda *_args, **_kwargs: source)

    def fake_collect(_db, _user, _source, _product):
        return ([{
            "type": "tool", "label": "授权库存", "tool": "inventory.query_available",
            "arguments": {"product_id": 9}, "fingerprint": "f" * 64,
            "totals": [], "sources": [], "source": _source.reference(),
        }], facts or {"product": {"product_id": 9, "product_name": "乙醇", "unit_id": 3}}, [])

    monkeypatch.setattr(bridge_module, "collect_reference_facts", fake_collect)
    if saved is not None:
        monkeypatch.setattr(conversation_store, "save_purchase_draft_bridge",
                            lambda _db, _user, _cid, value, **kwargs: saved.append((value, kwargs)) or value)
    if cleared is not None:
        monkeypatch.setattr(conversation_store, "clear_purchase_draft_bridge",
                            lambda _db, _user, _cid, **kwargs: cleared.append(kwargs) or 1)
    monkeypatch.setattr(drafts, "get_user_permission_codes",
                        lambda *_args: ["procurement.requests.write", "master.products.read",
                                        "warehouse.inventory.read", "procurement.rfqs.read"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])
    return bridge_module.DraftSource


def test_query_source_draft_asks_for_missing_quantity_and_persists_anchor(monkeypatch) -> None:
    saved = []
    DraftSource = _patch_draft_source(monkeypatch, saved=saved)
    source = DraftSource(kind="agent", message_id=5, task_id="t1", revision=2,
                         product_id=9, unit_id=3, product_name="乙醇", rfq_item_id=11)

    from app.modules.ai import conversation_store
    monkeypatch.setattr(conversation_store, "load_purchase_draft_bridge", lambda *_args, **_kwargs: None)
    from app.modules.ai import purchase_draft_bridge as bridge_module
    monkeypatch.setattr(bridge_module, "resolve_draft_source",
                        lambda *_args, **_kwargs: bridge_module.SourceResolution(source=source))

    async def fake_chat(_request, _settings, *, attachment_context, response_format):
        assert "服务端已核验的来源对象" in attachment_context[0]
        assert "只读参考" in attachment_context[0]
        return SimpleNamespace(answer=json.dumps({
            "purpose": "实验", "priority": "NORMAL", "currency_code": "CNY",
            "items": [{"requested_name": "", "product_id": None, "quantity": None}],
        }, ensure_ascii=False))

    monkeypatch.setattr(drafts, "chat", fake_chat)
    preview = _run_immediate(drafts.propose_purchase_request_draft(
        _source_database(), SimpleNamespace(id=5, department_id=2, status="ACTIVE"),
        "按刚才的信息整理采购申请", conversation_id=77))

    assert preview.missing_fields == ["第 1 项数量"]
    assert preview.confirmation_id is None
    assert preview.evidence[0]["source"]["product_id"] == 9
    assert saved and saved[0][0]["source"]["product_id"] == 9
    assert saved[0][0]["missing_fields"] == ["第 1 项数量"]


def test_follow_up_uses_pinned_source_and_clears_bridge(monkeypatch) -> None:
    from app.modules.ai.purchase_draft_bridge import DraftSource
    cleared = []
    source = DraftSource(kind="agent", message_id=5, task_id="t1", revision=2,
                         product_id=9, unit_id=3, product_name="乙醇", rfq_item_id=11)
    _patch_draft_source(monkeypatch, source=source, saved=[], cleared=cleared)
    from app.modules.ai import conversation_store
    bridge = {"state_version": 4, "contract_version": "1",
              "source": source.reference(),
              "requirements": {"purpose": "实验", "priority": "NORMAL", "currency_code": "CNY",
                               "items": [{"requested_name": "乙醇", "quantity": None, "unit_id": 3}]},
              "missing_fields": ["第 1 项数量"]}
    monkeypatch.setattr(conversation_store, "load_purchase_draft_bridge", lambda *_args, **_kwargs: bridge)

    async def fake_chat(_request, _settings, *, attachment_context, response_format):
        assert "上一轮已由用户提供但尚未补齐的需求" in attachment_context[0]
        return SimpleNamespace(answer=json.dumps({
            "purpose": "实验", "priority": "NORMAL", "currency_code": "CNY",
            "items": [{"requested_name": "乙醇", "product_id": None, "quantity": "50", "unit_id": 3}],
        }, ensure_ascii=False))

    monkeypatch.setattr(drafts, "chat", fake_chat)
    from app.modules.ai import action_proposals
    from datetime import datetime, timezone
    proposed = []
    monkeypatch.setattr(action_proposals, "propose_action",
                        lambda _db, _user, action_type, payload, *, idempotency_key, evidence=None:
                        proposed.append((action_type, payload, evidence)) or SimpleNamespace(
                            confirmation_id="f" * 32, preview_version=1,
                            expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    preview = _run_immediate(drafts.propose_purchase_request_draft(
        _source_database(), SimpleNamespace(id=5, department_id=2, status="ACTIVE"),
        "数量 50 升", conversation_id=77))

    assert preview.confirmation_id and proposed
    assert proposed[0][1]["items"][0]["product_id"] == 9
    assert proposed[0][1]["items"][0]["quantity"] == "50"
    assert proposed[0][2][0]["source"]["task_id"] == "t1"
    assert preview.evidence == proposed[0][2]
    assert cleared and cleared[0]["state_version"] == 4


def test_structured_form_keeps_matching_source_evidence(monkeypatch) -> None:
    DraftSource = _patch_draft_source(monkeypatch)
    source = DraftSource(kind="agent", message_id=5, task_id="t1", revision=2,
                         product_id=9, unit_id=3, product_name="乙醇", rfq_item_id=11)
    from app.modules.ai import conversation_store
    monkeypatch.setattr(conversation_store, "load_purchase_draft_bridge", lambda *_args, **_kwargs: None)
    from app.modules.ai import purchase_draft_bridge as bridge_module
    monkeypatch.setattr(bridge_module, "resolve_draft_source",
                        lambda *_args, **_kwargs: bridge_module.SourceResolution(source=source))
    from app.modules.purchase_requests.schema import PurchaseRequestCreate
    draft = PurchaseRequestCreate.model_validate({
        "department_id": 2, "purpose": "实验",
        "items": [{"requested_name": "乙醇", "product_id": 9, "quantity": "50", "unit_id": 3}],
    })
    from app.modules.ai import action_proposals
    from datetime import datetime, timezone
    proposed = []
    monkeypatch.setattr(action_proposals, "propose_action",
                        lambda _db, _user, action_type, payload, *, idempotency_key, evidence=None:
                        proposed.append(evidence) or SimpleNamespace(
                            confirmation_id="f" * 32, preview_version=1,
                            expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    preview = _run_immediate(drafts.propose_purchase_request_draft(
        _source_database(), SimpleNamespace(id=5, department_id=2, status="ACTIVE"),
        draft=draft, conversation_id=77))

    assert proposed and proposed[0][0]["source"]["product_id"] == 9
    assert preview.evidence[0]["source"]["product_id"] == 9


def test_ambiguous_query_returns_clarification_without_calling_model(monkeypatch) -> None:
    from app.modules.ai import conversation_store, purchase_draft_bridge as bridge_module
    monkeypatch.setattr(conversation_store, "get_owned_conversation", lambda *_args: object())
    monkeypatch.setattr(conversation_store, "load_purchase_draft_bridge", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bridge_module, "resolve_draft_source",
                        lambda *_args, **_kwargs: bridge_module.SourceResolution(reason="AMBIGUOUS"))
    monkeypatch.setattr(drafts, "get_user_permission_codes", lambda *_args: ["procurement.requests.write"])
    monkeypatch.setattr(drafts, "get_user_role_codes", lambda *_args: [])
    async def fail_chat(*_args, **_kwargs):
        raise AssertionError("多规格来源不得直接调用模型")
    monkeypatch.setattr(drafts, "chat", fail_chat)

    preview = _run_immediate(drafts.propose_purchase_request_draft(
        _Database(), SimpleNamespace(id=5, department_id=2, status="ACTIVE"),
        "按刚才的信息整理采购申请", conversation_id=77))
    assert preview.missing_fields == ["查询来源"]
    assert "多个产品规格" in (preview.clarification_question or "")
    assert preview.confirmation_id is None


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
