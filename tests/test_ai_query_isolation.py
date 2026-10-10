"""查询目录、执行证据与历史回放的当前身份隔离回归。"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai import agent_tools, controller, conversation_store, history_access, multi_intent, routing, service, text2sql
from app.modules.ai.catalog import CATALOG
from app.modules.ai.model import AIConversation, AIConversationState, AIMessage
from app.modules.ai.schema import TaskStatus
from app.modules.system.model import User
from scripts.seed_demo_accounts import ROLE_SCOPES
from tests.test_agent_read_tools import tool_db
from tests.test_ai_multi_intent import decision, product_task


@pytest.mark.parametrize("dataset", CATALOG)
def test_every_dataset_rejects_missing_or_revoked_permission(monkeypatch, dataset):
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: [])
    metric = "records" if "records" in CATALOG[dataset].metrics else "count"
    with pytest.raises(BusinessValidationError, match="没有执行"):
        text2sql._validate_plan(None, SimpleNamespace(id=7), text2sql.QueryPlan(dataset=dataset, metric=metric, time_field=None,
            filters=[text2sql.QueryFilter(field="product_id", operator="in", value=[1])] if dataset == "inventory_movement_trace" else []))


@pytest.mark.parametrize("dataset", ["inventory", "inventory_by_batch", "inventory_transactions", "inventory_movement_trace"])
def test_technical_role_cannot_read_generic_inventory(monkeypatch, dataset):
    permissions = ROLE_SCOPES["TECHNICAL"]
    assert "warehouse.inventory.read" not in permissions
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: ["TECHNICAL"])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: permissions)
    monkeypatch.setattr(agent_tools, "get_user_role_codes", lambda *_: ["TECHNICAL"])
    monkeypatch.setattr(agent_tools, "get_user_permission_codes", lambda *_: permissions)
    monkeypatch.setattr(agent_tools, "get_settings", lambda: SimpleNamespace(agent_enabled=True))
    assert "inventory.query_available" not in {item["name"] for item in agent_tools.list_tools(None, SimpleNamespace(id=7))}
    metric = "records" if "records" in CATALOG[dataset].metrics else "count"
    with pytest.raises(BusinessValidationError):
        text2sql._validate_plan(None, SimpleNamespace(id=7), text2sql.QueryPlan(dataset=dataset, metric=metric, time_field=None,
            filters=[text2sql.QueryFilter(field="product_id", operator="in", value=[1])] if dataset == "inventory_movement_trace" else []))


def citation_for(db, user, plan):
    fetched = db.execute(text2sql.build_statement(plan, db, user)).mappings().all()
    raw = [{str(k): text2sql._serialize(v) for k, v in row.items()} for row in fetched[:plan.limit]]
    return {"type": "text2sql", "query_plan": plan.model_dump(mode="json"),
            "source_records": text2sql._source_records(plan.dataset, raw),
            "query_trace": {"rows": [{k: v for k, v in row.items() if not k.startswith("_source_")} for row in raw],
                            "truncated": len(fetched) > plan.limit}}


def test_inventory_aggregate_and_sources_use_current_warehouse_scope(tool_db, monkeypatch):
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: ["warehouse.inventory.read"])
    user = SimpleNamespace(id=7)
    plan = text2sql.QueryPlan(dataset="inventory", metric="sum_quantity", group_by="warehouse")
    citation = citation_for(tool_db, user, plan)
    assert {row["warehouse"] for row in citation["query_trace"]["rows"]} == {"本人仓库", "公共仓库"}
    assert history_access.query_accessible(tool_db, user, citation)
    tool_db.execute(text("UPDATE warehouses SET manager_id=8 WHERE id=1"))
    assert not history_access.query_accessible(tool_db, user, citation)


def test_quote_statistics_are_isolated_by_requester(tool_db, monkeypatch):
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: ["procurement.rfqs.read"])
    plan = text2sql.QueryPlan(dataset="supplier_quotes", metric="count")
    own = citation_for(tool_db, SimpleNamespace(id=7), plan)
    other = citation_for(tool_db, SimpleNamespace(id=8), plan)
    assert own["query_trace"]["rows"] == [{"metric_value": 14}]
    assert other["query_trace"]["rows"] == [{"metric_value": 0}]
    assert not history_access.query_accessible(tool_db, SimpleNamespace(id=8), own)


@pytest.mark.parametrize("department_id,expected", [(10, [1]), (None, [1])])
def test_approved_unquoted_requests_do_not_cross_department_or_applicant(tool_db, monkeypatch, department_id, expected):
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    tool_db.execute(text("CREATE TABLE purchase_requests (id INTEGER PRIMARY KEY, request_no TEXT, purpose TEXT, priority TEXT, approved_at TEXT, expected_date TEXT, status TEXT, department_id INTEGER, applicant_id INTEGER)"))
    tool_db.execute(text("CREATE TABLE purchase_request_items (id INTEGER PRIMARY KEY, request_id INTEGER)"))
    tool_db.execute(text("ALTER TABLE rfqs ADD COLUMN source_request_id INTEGER"))
    tool_db.execute(text("ALTER TABLE rfq_items ADD COLUMN source_request_item_id INTEGER"))
    tool_db.execute(text("INSERT INTO purchase_requests VALUES (1, 'OWN', '本人', 'NORMAL', NULL, NULL, 'APPROVED', 10, 7), (2, 'OTHER', '其他部门', 'NORMAL', NULL, NULL, 'APPROVED', 20, 8)"))
    plan = text2sql.QueryPlan(dataset="approved_requests_without_rfq", metric="records", time_field=None)
    rows = tool_db.execute(text2sql.build_statement(plan, tool_db, SimpleNamespace(id=7, department_id=department_id))).mappings().all()
    assert [row["_source_record_id"] for row in rows] == expected


def test_single_query_history_hides_answer_and_sources_after_revocation(tool_db, monkeypatch):
    permissions = ["warehouse.inventory.read"]
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: permissions)
    user = SimpleNamespace(id=7)
    citation = citation_for(tool_db, user, text2sql.QueryPlan(dataset="inventory", metric="count"))
    message = SimpleNamespace(message_role="ASSISTANT", content="旧库存数字", citations=[citation])
    assert history_access.visible_message(tool_db, user, message)[0] == "旧库存数字"
    permissions.clear()
    content, sources = history_access.visible_message(tool_db, user, message)
    assert "重新查询" in content and sources == []
    message.message_role, message.content = "USER", "查库存数量"
    assert history_access.visible_message(tool_db, user, message) == ("查库存数量", [])


def test_waiting_batch_evidence_is_rechecked_after_permission_revocation(tool_db, monkeypatch):
    tool_db.execute(text("INSERT INTO md_products VALUES (3, '测试甲醇', 'ACTIVE', 'P-MET', '分析纯', '20kg', 1)"))
    batch = asyncio.run(multi_intent.execute_batch(tool_db, SimpleNamespace(id=7), decision(
        product_task(slots={"product_keyword": "测试"}), product_task("t2", slots={"product_keyword": "测试"})), Settings(_env_file=None)))
    assert all(task.status == TaskStatus.WAITING_INPUT for task in batch.tasks)
    assert multi_intent.history_accessible(tool_db, SimpleNamespace(id=7), batch.model_dump(mode="json"))
    monkeypatch.setattr(agent_tools, "get_user_permission_codes", lambda *_: [])
    assert not multi_intent.history_accessible(tool_db, SimpleNamespace(id=7), batch.model_dump(mode="json"))


def test_history_checks_source_identity_even_when_visible_rows_match(tool_db, monkeypatch):
    monkeypatch.setattr(text2sql, "get_user_role_codes", lambda *_: [])
    monkeypatch.setattr(text2sql, "get_user_permission_codes", lambda *_: ["warehouse.inventory.read"])
    citation = citation_for(tool_db, SimpleNamespace(id=7), text2sql.QueryPlan(dataset="inventory", metric="count"))
    citation["source_records"] = [{"record_id": 999, "label": "旧授权来源"}]
    assert not history_access.query_accessible(tool_db, SimpleNamespace(id=7), citation)


def test_cross_user_cannot_load_conversation_or_routing_context(db_session):
    users = list(db_session.scalars(select(User).where(User.status == "ACTIVE").limit(2)))
    assert len(users) == 2
    conversation = AIConversation(user_id=users[0].id, title="私有查询", business_scene="GENERAL", status="ACTIVE")
    db_session.add(conversation)
    db_session.flush()
    for load in (conversation_store.list_messages, routing.conversation_context):
        with pytest.raises(BusinessValidationError, match="无权访问"):
            load(db_session, users[1], conversation.id)


def test_revoked_history_is_not_sent_to_understanding_model(db_session, monkeypatch):
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    conversation = AIConversation(user_id=user.id, title="权限撤销", business_scene="GENERAL", status="ACTIVE")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(AIMessage(conversation_id=conversation.id, message_role="ASSISTANT", content="不可再见的付款数字",
                            citations=[{"type": "text2sql"}]))
    db_session.flush()
    monkeypatch.setattr(history_access, "query_accessible", lambda *_: False)
    context = routing.conversation_context(db_session, user, conversation.id)
    assert "不可再见" not in str(context)
    assert context["memory"] == {} and context["query_plan"] is None
