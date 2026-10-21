"""AI clarification state schema and lifecycle checks."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai import conversation_store, schema
from app.modules.ai.model import AIConversation, AIConversationState, AIMessage


def test_chat_answer_is_bound_to_saved_option_and_invalid_answer_keeps_state(monkeypatch):
    from app.modules.ai import capabilities, routing, service

    user = SimpleNamespace(id=7)
    pending = schema.PendingClarification(
        state_id="a" * 32, question_hash="b" * 64, slot="analytics_granularity",
        question="按订单还是明细统计？", options=["按订单数", "按订单行数"],
        created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        permission_hash="c" * 64, state_version=5, contract_version="1")
    cleared = []
    contexts = []
    monkeypatch.setattr(conversation_store, "load_pending_clarification", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(conversation_store, "clear_pending_clarification", lambda *args, **kwargs: cleared.append(kwargs))
    monkeypatch.setattr(routing, "conversation_context", lambda *_: {"memory": {"pending_clarification": pending.model_dump(mode="json")}})
    monkeypatch.setattr(routing, "with_pending_clarification", lambda _db, _user, _cid, context, _pending:
                        {**context, "pending_clarification": {"slot": "analytics_granularity",
                                                               "original_question": "统计采购数量"}})
    monkeypatch.setattr(capabilities, "build_capability_manifest", lambda *_: {"version": "test"})
    async def understand(question, context, **kwargs):
        contexts.append((question, context))
        if question == "取消查询":
            return schema.Understanding(purpose="clarify", dialogue_action="cancel")
        return schema.Understanding(purpose="query", execution_mode="query", tasks=["analytics"],
            sub_tasks=[{"id": "t1", "kind": "analytics", "question": "按订单数统计采购数量"}])
    monkeypatch.setattr(routing, "understand", understand)

    def run_immediate(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        raise AssertionError("测试替身不应挂起等待")

    invalid = run_immediate(service._classify_chat_intent(
        SimpleNamespace(commit=lambda: None), "大概按订单吧", user=user,
        data=schema.AIChatRequest(conversation_id=12, messages=[{"role": "user", "content": "大概按订单吧"}])))
    assert invalid.intent is schema.Intent.CLARIFY
    assert not cleared and len(contexts) == 1

    with pytest.raises(BusinessValidationError, match="先回答或取消"):
        run_immediate(service._classify_chat_intent(
            SimpleNamespace(commit=lambda: None), "重试失败项", user=user,
            data=schema.AIChatRequest(conversation_id=12, retry_failed=True,
                                      messages=[{"role": "user", "content": "重试失败项"}])))

    resolved = run_immediate(service._classify_chat_intent(
        SimpleNamespace(commit=lambda: None), "按订单数", user=user,
        data=schema.AIChatRequest(conversation_id=12, messages=[{"role": "user", "content": "按订单数"}])))
    assert resolved.intent is schema.Intent.QUERY
    assert contexts[1][0] == "按订单数"
    assert contexts[1][1]["pending_clarification"]["slot"] == "analytics_granularity"
    assert cleared[0]["state_id"] == pending.state_id
    assert cleared[0]["expected_state_version"] == pending.state_version

    cleared.clear()
    monkeypatch.setattr(routing, "read_ticket", lambda *_: schema.Understanding(
        purpose="query", execution_mode="query", tasks=["analytics"],
        sub_tasks=[{"id": "t1", "kind": "analytics", "question": "按订单数统计采购数量"}]))
    monkeypatch.setattr(routing, "read_ticket_pending_state_id", lambda *_: "d" * 32)
    with pytest.raises(BusinessValidationError, match="澄清状态"):
        run_immediate(service._classify_chat_intent(
            SimpleNamespace(commit=lambda: None), "按订单数", user=user,
            data=schema.AIChatRequest(conversation_id=12, route_token="ticket",
                                      messages=[{"role": "user", "content": "按订单数"}])))
    assert not cleared

    cancelled = run_immediate(service._classify_chat_intent(
        SimpleNamespace(commit=lambda: None), "取消查询", user=user,
        data=schema.AIChatRequest(conversation_id=12, messages=[{"role": "user", "content": "取消查询"}])))
    assert cancelled.intent is schema.Intent.CLARIFY
    assert cleared[0]["state_id"] == pending.state_id


def test_clarification_output_requires_a_bound_slot_and_finite_options():
    pending = schema.Understanding(
        purpose="clarify", question="按订单还是明细统计？",
        clarification_slot="analytics_granularity",
        clarification_options=["按订单数", "按订单行数"],
    )
    assert pending.execution_mode == "none"
    with pytest.raises(ValueError):
        schema.Understanding(purpose="clarify", question="按订单还是明细？", clarification_options=["按订单数"])
    with pytest.raises(ValueError):
        schema.Understanding(purpose="clarify", question="按订单还是明细？",
                             clarification_slot="analytics_granularity", clarification_options=["按订单数"])
    with pytest.raises(ValueError):
        schema.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"],
                             clarification_slot="product_keyword", clarification_options=["乙醇", "甲醇"])


@pytest.fixture
def clarification_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sys_users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ai_conversations (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title VARCHAR(255), business_scene VARCHAR(64) NOT NULL, permission_snapshot JSON NOT NULL, status VARCHAR(20) NOT NULL, pinned BOOLEAN DEFAULT 0 NOT NULL, last_message_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        connection.execute(text("CREATE TABLE ai_conversation_state (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL UNIQUE, thread_id VARCHAR(255) NOT NULL UNIQUE, memory_state JSON, query_plan JSON, query_trace JSON, permission_snapshot JSON, attachment_refs JSON, state_version INTEGER DEFAULT 1 NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
        connection.execute(text("CREATE TABLE ai_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL, message_role VARCHAR(20) NOT NULL, content TEXT NOT NULL, citations JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"))
    db = Session(engine, expire_on_commit=False)
    db.add(AIConversation(id=1, user_id=7, title="test", business_scene="GENERAL", status="ACTIVE"))
    db.add(AIConversationState(conversation_id=1, thread_id="ai:7:1", state_version=4,
                               memory_state={"batch_tasks": [{"id": "t1"}], "other": "keep"}))
    db.add(AIMessage(conversation_id=1, message_role="USER", content="统计采购数量"))
    db.commit()
    monkeypatch.setattr(conversation_store, "conversation_state_enabled", lambda *_: True)
    monkeypatch.setattr(conversation_store, "permission_snapshot", lambda *_: {"roles": ["BUYER"], "permissions": ["ai.workspace.read"]})
    yield db
    db.close()
    engine.dispose()


def test_pending_state_is_versioned_owned_and_merged_with_other_memory(clarification_db):
    user = SimpleNamespace(id=7)
    decision = schema.Understanding(purpose="clarify", question="按订单还是明细统计？",
        clarification_slot="analytics_granularity", clarification_options=["按订单数", "按订单行数"])

    pending = conversation_store.save_pending_clarification(
        clarification_db, user, 1, "统计采购数量", decision)
    state = clarification_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    assert pending.state_version == 5 and state.state_version == 5
    assert pending.state_id in clarification_db.execute(text("SELECT memory_state FROM ai_conversation_state WHERE conversation_id=1")).scalar_one()
    assert state.memory_state["batch_tasks"] == [{"id": "t1"}]
    assert "original_question" not in state.memory_state["pending_clarification"]
    assert conversation_store.load_pending_clarification(clarification_db, user, 1) == pending
    assert pending.state_id in clarification_db.execute(text("SELECT memory_state FROM ai_conversation_state WHERE conversation_id=1")).scalar_one()
    clarification_db.refresh(state)
    assert state.memory_state.get("pending_clarification", {}).get("state_id") == pending.state_id

    with pytest.raises(BusinessValidationError, match="版本"):
        conversation_store.clear_pending_clarification(
            clarification_db, user, 1, state_id=pending.state_id, expected_state_version=4)
    clarification_db.expire_all()
    cleared_version = conversation_store.clear_pending_clarification(
        clarification_db, user, 1, state_id=pending.state_id, expected_state_version=5)
    state = clarification_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    assert cleared_version == 6 and "pending_clarification" not in state.memory_state
    assert state.memory_state["batch_tasks"] == [{"id": "t1"}]


def test_pending_context_restores_original_question_from_owned_messages(clarification_db):
    from app.modules.ai import routing

    user = SimpleNamespace(id=7)
    decision = schema.Understanding(purpose="clarify", question="按订单还是明细统计？",
        clarification_slot="analytics_granularity", clarification_options=["按订单数", "按订单行数"])
    pending = conversation_store.save_pending_clarification(
        clarification_db, user, 1, "统计采购数量", decision)
    context = routing.with_pending_clarification(clarification_db, user, 1, {}, pending)
    assert context["pending_clarification"]["original_question"] == "统计采购数量"
    assert context["pending_clarification"]["slot"] == "analytics_granularity"


def test_pending_state_expiry_and_permission_change_fail_closed(clarification_db, monkeypatch):
    user = SimpleNamespace(id=7)
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    decision = schema.Understanding(purpose="clarify", question="按订单还是明细统计？",
        clarification_slot="analytics_granularity", clarification_options=["按订单数", "按订单行数"])
    expired = conversation_store.save_pending_clarification(
        clarification_db, user, 1, "统计采购数量", decision, now=now, ttl_seconds=1)
    assert expired.expires_at == now + timedelta(seconds=1)
    raw_state = clarification_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    assert raw_state.memory_state["pending_clarification"]["state_id"] == expired.state_id
    with pytest.raises(BusinessValidationError, match="过期"):
        conversation_store.load_pending_clarification(clarification_db, user, 1, now=now + timedelta(seconds=2))
    state = clarification_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    assert "pending_clarification" not in state.memory_state

    active = conversation_store.save_pending_clarification(clarification_db, user, 1, "统计采购数量", decision, now=now)
    monkeypatch.setattr(conversation_store, "conversation_state_enabled", lambda *_: True)
    monkeypatch.setattr(conversation_store, "permission_snapshot", lambda *_: {"roles": ["BUYER"], "permissions": []})
    with pytest.raises(BusinessValidationError, match="权限"):
        conversation_store.load_pending_clarification(clarification_db, user, 1, now=now + timedelta(seconds=1))


def test_pending_state_is_scoped_to_owner_and_old_conversations_remain_usable(clarification_db):
    owner = SimpleNamespace(id=7)
    stranger = SimpleNamespace(id=8)
    assert conversation_store.load_pending_clarification(clarification_db, owner, 1) is None
    with pytest.raises(BusinessValidationError):
        conversation_store.load_pending_clarification(clarification_db, stranger, 1)


def test_corrupt_pending_state_is_removed_instead_of_masking_original_error(clarification_db):
    user = SimpleNamespace(id=7)
    state = clarification_db.scalar(select(AIConversationState).where(AIConversationState.conversation_id == 1))
    state.memory_state = {"other": "preserve", "pending_clarification": {"state_id": "broken"}}
    state.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    clarification_db.flush()
    with pytest.raises(BusinessValidationError, match="澄清状态无效"):
        conversation_store.load_pending_clarification(clarification_db, user, 1)
    clarification_db.refresh(state)
    assert "pending_clarification" not in state.memory_state
    assert state.memory_state["other"] == "preserve"
