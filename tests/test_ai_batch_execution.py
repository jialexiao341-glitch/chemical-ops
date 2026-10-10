"""验证批次进度、取消持久化、总超时与只重试失败项，不调用外部模型。"""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai import multi_intent as multi, routing, service, text2sql
from app.modules.ai.model import AIMessage
from app.modules.ai.schema import AIChatMessage, AIChatRequest
from app.modules.ai.schema import BatchStatus, TaskStatus
from app.modules.system.model import User
from tests.test_ai_multi_intent import decision, product_task
from tests.test_agent_read_tools import tool_db
from tests.test_agent_runtime import USER


def test_total_timeout_preserves_finished_item_and_stops_remaining_work(tool_db, monkeypatch):
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(multi, "plan_analytics", stalled)
    progress = []
    async def record(snapshot):
        progress.append(snapshot)
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task(),
        {"id": "t2", "kind": "analytics", "question": "统计前项库存", "depends_on": ["t1"]}),
        Settings(_env_file=None, agent_task_timeout_seconds=1), on_progress=record))
    assert batch.status == BatchStatus.PARTIAL
    assert [task.status for task in batch.tasks] == [TaskStatus.SUCCEEDED, TaskStatus.FAILED]
    assert batch.tasks[1].error_code == "TASK_TIMEOUT" and batch.tasks[1].evidence == []
    assert progress[0]["completed"] == 0 and progress[-1]["completed"] == 1
    assert any(snapshot["tasks"][1]["status"] == "RUNNING" for snapshot in progress)


def test_retry_only_failed_items_and_rechecks_retained_evidence(tool_db, monkeypatch):
    route = decision(product_task(), product_task("t2"))
    first = asyncio.run(multi.execute_batch(tool_db, USER, route, Settings(_env_file=None)))
    first.tasks[1] = multi.TaskResult(id="t2", kind="inventory", question=route.sub_tasks[1].question,
        status=TaskStatus.FAILED, execution_plan={"slots": route.sub_tasks[1].slots.model_dump(mode="json")})
    calls = []
    execute = multi.execute_product_task
    def record(db, user, task, *args):
        calls.append(task.id)
        return execute(db, user, task, *args)
    monkeypatch.setattr(multi, "execute_product_task", record)
    retried = asyncio.run(multi.execute_batch(tool_db, USER, route, Settings(_env_file=None),
        previous_tasks=[task.model_dump(mode="json") for task in first.tasks], retry_failed=True))
    assert calls == ["t2"] and retried.status == BatchStatus.SUCCEEDED
    assert retried.tasks[0] == first.tasks[0]
    tool_db.execute(text("UPDATE warehouses SET manager_id=8 WHERE id=1"))
    with pytest.raises(BusinessValidationError, match="权限、范围或数据已变化"):
        asyncio.run(multi.execute_batch(tool_db, USER, route, Settings(_env_file=None),
            previous_tasks=[task.model_dump(mode="json") for task in first.tasks], retry_failed=True))
    assert calls == ["t2"]


def test_disconnect_saves_partial_cancelled_batch_then_retry_skips_finished_query(db_session, monkeypatch):
    route = decision({"id": "t1", "kind": "analytics", "question": "统计采购订单数量"},
                     {"id": "t2", "kind": "analytics", "question": "统计采购申请数量"})
    plans, executed = [], []
    async def understand(*args, **kwargs):
        return route
    async def plan(db, user, task, settings, **kwargs):
        plans.append(task.id)
        return text2sql.QueryPlan(dataset="purchase_orders" if task.id == "t1" else "purchase_requests", metric="count")
    async def no_rewrite(*args):
        return None
    original = service._run_text2sql_for_chat
    stall = True
    async def execute(db, user, question, *args, **kwargs):
        executed.append(question)
        if question == "统计采购申请数量" and stall:
            await asyncio.Event().wait()
        return await original(db, user, question, *args, **kwargs)
    monkeypatch.setattr(routing, "understand", understand)
    monkeypatch.setattr(multi, "plan_analytics", plan)
    monkeypatch.setattr(service, "_rewrite_text2sql_answer", no_rewrite)
    monkeypatch.setattr(service, "_run_text2sql_for_chat", execute)
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    async def run():
        nonlocal stall
        stream = service.stream_chat_for_user(db_session, user,
            AIChatRequest(messages=[AIChatMessage(role="user", content="分别统计订单及申请数量")]))
        while True:
            frame = await anext(stream)
            if frame.startswith("event: progress"):
                snapshot = json.loads(frame.split("data: ", 1)[1])
                if snapshot["completed"] == 1:
                    break
        await stream.aclose()
        latest = db_session.scalar(select(AIMessage).where(AIMessage.conversation_id == snapshot["conversation_id"],
                                    AIMessage.message_role == "ASSISTANT").order_by(AIMessage.id.desc()))
        batch = latest.citations[0]["batch"]
        assert [task["status"] for task in batch["tasks"]] == ["SUCCEEDED", "CANCELLED"]
        assert batch["status"] == "PARTIAL"
        stall = False
        plans.clear()
        executed.clear()
        retry = AIChatRequest(conversation_id=snapshot["conversation_id"], retry_failed=True,
                             messages=[AIChatMessage(role="user", content="重试未完成项")])
        frames = [frame async for frame in service.stream_chat_for_user(db_session, user, retry)]
        done = next(json.loads(frame.split("data: ", 1)[1]) for frame in frames if frame.startswith("event: done"))
        assert done["batch_result"]["status"] == "SUCCEEDED"
        assert plans == ["t2"] and executed == ["统计采购申请数量"]
        other = db_session.scalar(select(User).where(User.username == "system_admin"))
        assert other is not None and other.id != user.id
        with pytest.raises(BusinessValidationError, match="会话不存在或无权访问"):
            multi.retry_decision(db_session, other, snapshot["conversation_id"])
    asyncio.run(run())


def test_retry_without_batch_returns_stream_error_without_query(db_session):
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    async def run():
        return [frame async for frame in service.stream_chat_for_user(db_session, user,
            AIChatRequest(retry_failed=True, messages=[AIChatMessage(role="user", content="重试")]))]
    frames = asyncio.run(run())
    assert len(frames) == 1 and frames[0].startswith("event: error")


def test_retry_rejects_new_attachments_before_restoring_batch(db_session):
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    async def run():
        return [frame async for frame in service.stream_chat_for_user(db_session, user,
            AIChatRequest(retry_failed=True, attachment_file_ids=[123],
                messages=[AIChatMessage(role="user", content="重试")]))]
    frames = asyncio.run(run())
    assert len(frames) == 1 and "修改附件或条件请重新发起查询" in frames[0]


def test_retained_document_rechecks_parsed_status_and_excerpt(db_session):
    from app.modules.doc_kb.model import AiDocument, AiDocumentSection
    document = AiDocument(cas_no=f"test-{uuid4().hex[:20]}", doc_type="MSDS", source_bucket="test",
                          object_key="batch-retry-test", parse_status="PARSED")
    db_session.add(document)
    db_session.flush()
    section = AiDocumentSection(document_id=document.id, cas_no=document.cas_no, doc_type="MSDS",
                                section_key="SECTION 9", content="验收用文档摘录")
    db_session.add(section)
    db_session.flush()
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    report = {"status": "SUCCEEDED", "tasks": [{"id": "t1", "kind": "document",
        "question": "查询乙醇资料", "status": "SUCCEEDED", "citations": [{
            "document_id": document.id, "section_id": section.id, "content": section.content}]}]}
    assert multi.history_accessible(db_session, user, report)
    section.content = "已修订的文档摘录"
    db_session.flush()
    assert not multi.history_accessible(db_session, user, report)
    section.content = report["tasks"][0]["citations"][0]["content"]
    document.parse_status = "REJECTED"
    db_session.flush()
    assert not multi.history_accessible(db_session, user, report)
