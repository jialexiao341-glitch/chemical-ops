"""采购草稿来源锚点：只接受本人已完成查询，并按会话版本失效。"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai import conversation_store, purchase_draft_bridge as bridge
from app.modules.ai.model import AIAgentTask, AIConversation, AIConversationState, AIMessage


CATALOG_RESULT = {
    "tool": "catalog.search_products", "keyword": "乙醇", "total_rows": 1, "truncated": False,
    "rows": [{"product_id": 9, "product_name": "乙醇", "unit_id": 3}], "sources": [],
}
INVENTORY_RESULT = {
    "tool": "inventory.query_available", "observed_at": "2026-10-25T02:00:00+00:00",
    "product_id": 9, "total_rows": 0, "truncated": False, "scope": "授权仓库",
    "totals": [], "rows": [], "sources": [], "warnings": [],
}
COMPARE_RESULT = {
    "tool": "supplier_quotes.compare", "observed_at": "2026-10-25T02:00:00+00:00",
    "as_of": "2026-10-25", "product_id": 9, "rfq_id": 5, "rfq_no": "RFQ-0005",
    "rfq_item_id": 11, "scope": "同一询价明细", "total_rows": 1, "truncated": False,
    "rows": [{"supplier_name": "甲", "unit_price": "10.00", "currency_code": "CNY",
              "unit_name": "升", "rank": 1}], "sources": [],
}


def _trace():
    return [
        {"step": 1, "action": "call_tool", "tool": "catalog.search_products",
         "arguments": {"keyword": "乙醇", "limit": 10}, "status": "SUCCEEDED", "result": CATALOG_RESULT},
        {"step": 2, "action": "call_tool", "tool": "inventory.query_available",
         "arguments": {"product_id": 9}, "status": "SUCCEEDED", "result": INVENTORY_RESULT},
        {"step": 3, "action": "call_tool", "tool": "supplier_quotes.compare",
         "arguments": {"product_id": 9, "rfq_item_id": 11}, "status": "SUCCEEDED", "result": COMPARE_RESULT},
        {"step": 4, "action": "finish", "status": "SUCCEEDED", "evidence_steps": [1, 2, 3]},
    ]


@pytest.fixture
def bridge_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ai_conversations (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "title VARCHAR(255), business_scene VARCHAR(64) NOT NULL, permission_snapshot JSON NOT NULL, "
            "status VARCHAR(20) NOT NULL, pinned BOOLEAN DEFAULT 0 NOT NULL, last_message_at DATETIME, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        connection.execute(text(
            "CREATE TABLE ai_conversation_state (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "conversation_id INTEGER NOT NULL UNIQUE, thread_id VARCHAR(255) NOT NULL UNIQUE, "
            "memory_state JSON, query_plan JSON, query_trace JSON, permission_snapshot JSON, "
            "attachment_refs JSON, state_version INTEGER DEFAULT 1 NOT NULL, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        connection.execute(text(
            "CREATE TABLE ai_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "conversation_id INTEGER NOT NULL, message_role VARCHAR(20) NOT NULL, content TEXT NOT NULL, "
            "citations JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
    AIAgentTask.__table__.create(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(AIConversation(id=1, user_id=7, title="test", business_scene="GENERAL", status="ACTIVE"))
    db.add(AIConversation(id=2, user_id=7, title="other", business_scene="GENERAL", status="ACTIVE"))
    db.commit()
    monkeypatch.setattr(conversation_store, "conversation_state_enabled", lambda *_: True)
    monkeypatch.setattr(conversation_store, "permission_snapshot", lambda *_: {"roles": [], "permissions": ["master.products.read"]})
    monkeypatch.setattr(bridge, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(bridge, "get_user_permission_codes",
                        lambda *_: ["procurement.requests.write", "master.products.read",
                                    "warehouse.inventory.read", "procurement.rfqs.read"])
    monkeypatch.setattr(bridge, "_validated_source",
                        lambda _db, source: replace(source, unit_id=3, product_name="乙醇"))
    yield db
    db.close()
    engine.dispose()


def _add_agent_message(db, *, task_id="t1", status="SUCCEEDED", revision=3, product_id=9,
                       conversation_id=1, owner_id=7, chat_conversation_id=1):
    payload = {"trace": _trace(), "chat": {"conversation_id": chat_conversation_id},
               "selected_product": product_id, "selected_rfq_item": 11}
    db.add(AIAgentTask(id=task_id, user_id=owner_id, status=status, revision=revision, payload=payload,
                       reply="完成", error_code=None, created_at=datetime(2026, 10, 25, 2),
                       updated_at=datetime(2026, 10, 25, 2)))
    message = AIMessage(conversation_id=conversation_id, message_role="ASSISTANT", content="查完了",
                        citations=[{"type": "agent_task", "task_id": task_id}])
    db.add(message)
    db.flush()
    return message


def _add_batch_message(db, *, tasks):
    message = AIMessage(conversation_id=1, message_role="ASSISTANT", content="批次完成",
                        citations=[{"type": "multi_intent", "batch": {"status": "COMPLETED", "tasks": tasks}}])
    db.add(message)
    db.flush()
    return message


def test_agent_query_resolves_source_and_bridge_is_versioned(bridge_db) -> None:
    message = _add_agent_message(bridge_db)
    resolution = bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1)
    assert resolution.reason is None
    source = resolution.source
    assert (source.kind, source.product_id, source.unit_id, source.rfq_item_id) == ("agent", 9, 3, 11)
    assert source.message_id == message.id and source.revision == 3
    assert source.anchors and all(anchor.get("fingerprint") for anchor in source.anchors)

    stored = conversation_store.save_purchase_draft_bridge(
        bridge_db, SimpleNamespace(id=7), 1, bridge.build_bridge(
            source, {"purpose": "实验", "items": [{"requested_name": "乙醇", "quantity": "50", "unit_id": 3}]},
            ["采购用途"], question="按刚才的信息整理采购申请"))
    state = bridge_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    assert stored["state_version"] == state.state_version == 2
    assert conversation_store.load_purchase_draft_bridge(bridge_db, SimpleNamespace(id=7), 1) == stored
    assert stored["source"]["product_id"] == 9


def test_source_is_scoped_to_owner_and_conversation(bridge_db) -> None:
    _add_agent_message(bridge_db, owner_id=8)
    assert bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1).reason == "NO_SOURCE"
    _add_agent_message(bridge_db, task_id="t2", chat_conversation_id=2)
    assert bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1).reason == "NO_SOURCE"


def test_unfinished_latest_query_does_not_fall_back(bridge_db) -> None:
    _add_agent_message(bridge_db, status="RUNNING")
    resolution = bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1)
    assert resolution.reason == "INCOMPLETE" and resolution.source is None


def test_batch_query_uses_tool_arguments_and_single_product(bridge_db) -> None:
    _add_batch_message(bridge_db, tasks=[{
        "id": "s1", "kind": "inventory", "question": "查乙醇库存", "status": "SUCCEEDED",
        "tool_calls": [
            {"tool": "catalog.search_products", "arguments": {"keyword": "乙醇"}},
            {"tool": "inventory.query_available", "arguments": {"product_id": 9}},
        ],
        "evidence": [CATALOG_RESULT, INVENTORY_RESULT],
    }])
    resolution = bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1)
    assert resolution.source is not None
    assert (resolution.source.kind, resolution.source.product_id, resolution.source.unit_id) == ("batch", 9, 3)


def test_batch_with_multiple_products_requires_clarification(bridge_db) -> None:
    _add_batch_message(bridge_db, tasks=[
        {"id": "s1", "kind": "inventory", "question": "查乙醇", "status": "SUCCEEDED",
         "tool_calls": [{"tool": "inventory.query_available", "arguments": {"product_id": 9}}],
         "evidence": [INVENTORY_RESULT]},
        {"id": "s2", "kind": "inventory", "question": "查甲醇", "status": "SUCCEEDED",
         "tool_calls": [{"tool": "inventory.query_available", "arguments": {"product_id": 10}}],
         "evidence": [INVENTORY_RESULT]},
    ])
    resolution = bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1)
    assert resolution.reason == "AMBIGUOUS" and resolution.source is None


def test_bridge_expires_and_rejects_stale_versions(bridge_db) -> None:
    source = bridge.DraftSource(kind="agent", message_id=1, task_id="t1", revision=1, product_id=9)
    now = datetime(2026, 10, 25, 2, tzinfo=timezone.utc)
    stored = conversation_store.save_purchase_draft_bridge(
        bridge_db, SimpleNamespace(id=7), 1, bridge.build_bridge(source, {"items": []}, ["数量"], question="q"),
        now=now, ttl_seconds=60)
    assert stored is not None
    assert conversation_store.load_purchase_draft_bridge(
        bridge_db, SimpleNamespace(id=7), 1, now=now + timedelta(seconds=61)) is None
    with pytest.raises(BusinessValidationError, match="已变化"):
        conversation_store.save_purchase_draft_bridge(
            bridge_db, SimpleNamespace(id=7), 1, bridge.build_bridge(source, {"items": []}, ["数量"], question="q"),
            expected_state_version=stored["state_version"] + 1, now=now)


def test_pinned_source_is_revalidated_by_task_revision(bridge_db) -> None:
    message = _add_agent_message(bridge_db)
    resolution = bridge.resolve_draft_source(bridge_db, SimpleNamespace(id=7), 1)
    raw = bridge.build_bridge(resolution.source, {"items": []}, ["数量"], question="q")
    assert bridge.restore_bridge_source(bridge_db, SimpleNamespace(id=7), 1, raw) is not None

    task = bridge_db.get(AIAgentTask, "t1")
    task.revision = 4
    bridge_db.flush()
    assert bridge.restore_bridge_source(bridge_db, SimpleNamespace(id=7), 1, raw) is None

    task.revision = 3
    task.status = "CANCELLED"
    bridge_db.flush()
    assert bridge.restore_bridge_source(bridge_db, SimpleNamespace(id=7), 1, raw) is None
    assert message.id
