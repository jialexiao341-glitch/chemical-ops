"""Queue-mode Agent control flow; model and role responses are explicit substitutes."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.core.config import Settings
from app.modules.ai import agent_runtime as runtime
from app.modules.ai.model import AIAgentTask, AIConversation, AIMessage
from app.modules.task_queue import service
from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock
from tests.test_agent_runtime import USER, task_db, chat_task_db, model_script, tool
from tests.test_agent_read_tools import allow_ai_workspace_permission, tool_db


@pytest.fixture
def queued_db(chat_task_db, monkeypatch):
    chat_task_db.autoflush = False
    for model in (TaskExecution, TaskOutbox, TaskResourceLock):
        model.__table__.create(chat_task_db.bind)
    settings = Settings(_env_file=None, openai_api_key="test-key", agent_execution_mode="database")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    from sqlalchemy.orm import Session
    monkeypatch.setattr(runtime, "SessionLocal", lambda: Session(chat_task_db.bind, autoflush=False))
    return chat_task_db


def accept(db):
    background = BackgroundTasks()
    task = runtime.schedule_async(db, USER, background, runtime.prepare_chat_task,
                                 runtime.ChatTaskCreate(question="查询测试乙醇库存"))
    assert background.tasks == [] and task.status == "RUNNING"
    execution = db.scalar(select(TaskExecution).where(TaskExecution.business_id == task.id))
    assert execution.status == "QUEUED"
    assert db.scalar(select(TaskOutbox).where(TaskOutbox.execution_id == execution.id)) is None
    return task, execution


def claim(db, execution, monkeypatch):
    current = service.claim_execution(db, execution.id, execution.delivery_generation, "test-worker", 60)
    monkeypatch.setenv("CHEMICALOPS_EXECUTION_ID", current.id)
    monkeypatch.setenv("CHEMICALOPS_EXECUTION_TOKEN", str(current.fencing_token))
    return current


def test_queue_chat_wait_and_manual_continue_create_a_new_generation(queued_db, model_script, monkeypatch):
    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    model_script[0].append({"action": "ask_user", "question": "请选择产品规格"})
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    assert queued_db.get(TaskExecution, execution.id).status == "WAITING_INPUT"
    waiting = runtime.get_task(queued_db, USER, task.id)
    assert waiting.status == "WAITING_INPUT"
    monkeypatch.delenv("CHEMICALOPS_EXECUTION_ID")
    monkeypatch.delenv("CHEMICALOPS_EXECUTION_TOKEN")
    continued = runtime.schedule_async(queued_db, USER, BackgroundTasks(), runtime.prepare_chat_continue,
        task.id, runtime.TaskContinue(question="测试乙醇", revision=waiting.revision))
    executions = list(queued_db.scalars(select(TaskExecution).where(TaskExecution.business_id == task.id)
                                      .order_by(TaskExecution.run_generation)))
    assert len(executions) == 2 and executions[1].run_generation > executions[0].run_generation
    assert service.claim_execution(queued_db, execution.id, 0, "duplicate", 60) is None
    current = claim(queued_db, executions[1], monkeypatch)
    model_script[0].extend([tool("catalog.search_products", keyword="测试乙醇"),
        tool("inventory.query_available", product_id=1), {"action": "finish", "evidence_steps": [3]}])
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    assert runtime.get_task(queued_db, USER, task.id).status == "SUCCEEDED"
    assert len(queued_db.scalars(select(AIMessage).where(AIMessage.message_role == "ASSISTANT")).all()) == 2


def test_cancel_queued_task_cannot_be_claimed(queued_db, monkeypatch):
    task, execution = accept(queued_db)
    cancelled = runtime.cancel_task(queued_db, USER, task.id)
    assert cancelled.status == "CANCELLED"
    queued_db.expire_all()
    assert queued_db.get(TaskExecution, execution.id).status == "CANCELLED"
    assert service.claim_execution(queued_db, execution.id, 0, "late-worker", 60) is None
    from sqlalchemy.orm import sessionmaker
    from app.modules.task_queue.worker import recover
    assert recover(sessionmaker(queued_db.bind, expire_on_commit=False), Settings(_env_file=None)) == 0


def test_enqueue_failure_rolls_back_chat_task_and_messages(queued_db, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated enqueue failure")
    monkeypatch.setattr(service, "enqueue", fail)
    with pytest.raises(RuntimeError):
        accept(queued_db)
    queued_db.rollback()
    assert queued_db.scalars(select(AIAgentTask)).all() == []
    assert queued_db.scalars(select(AIConversation)).all() == []
    assert queued_db.scalars(select(AIMessage)).all() == []


def test_recovery_uses_latest_revision_without_creating_messages(queued_db, model_script, monkeypatch):
    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    original_decide = runtime._decide
    calls = []
    async def interrupted(state, catalog, settings):
        calls.append(state.revision)
        if len(calls) > 1:
            raise KeyboardInterrupt("simulated process termination after a checkpoint")
        return await original_decide(state, catalog, settings)
    monkeypatch.setattr(runtime, "_decide", interrupted)
    model_script[0].append(tool("catalog.search_products", keyword="测试乙醇"))
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    execution = queued_db.get(TaskExecution, execution.id)
    assert execution.business_revision > execution.run_generation
    service.finish(queued_db, execution.id, execution.fencing_token, status="FAILED", retryable=True)
    execution.next_attempt_at = None
    queued_db.commit()
    current = claim(queued_db, execution, monkeypatch)
    monkeypatch.setattr(runtime, "_decide", original_decide)
    model_script[0].extend([tool("inventory.query_available", product_id=1),
                            {"action": "finish", "evidence_steps": [2]}])
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    result = runtime.get_task(queued_db, USER, task.id)
    assert result.status == "SUCCEEDED" and len(result.trace) == 3, (result.error_code, result.trace)
    assert len(queued_db.scalars(select(AIMessage)).all()) == 2
    assert service.claim_execution(queued_db, execution.id, 0, "obsolete", 60) is None


@pytest.mark.parametrize('combined', [False, True])
def test_selected_rfq_continuation_recovers_after_product_checkpoint(queued_db, model_script, monkeypatch, combined):
    """候选选择的新一代执行崩溃后，从已核验产品继续，不能重解释编号或重复查产品。"""
    from sqlalchemy import text
    queued_db.execute(text("INSERT INTO rfqs VALUES (4, 'LEGACY-B', 7, 'SENT')"))
    queued_db.execute(text("INSERT INTO rfq_items VALUES (41, 4, 1, '工业级', NULL)"))
    queued_db.commit()
    task = runtime.schedule_async(queued_db, USER, BackgroundTasks(), runtime.prepare_chat_task,
                                 runtime.ChatTaskCreate(question='查测试乙醇库存并比较报价' if combined else '比较测试乙醇报价'))
    execution = queued_db.scalar(select(TaskExecution).where(TaskExecution.business_id == task.id))
    current = claim(queued_db, execution, monkeypatch)
    model_script[0].extend([tool('catalog.search_products', keyword='测试乙醇'),
                           tool('supplier_quotes.find_rfq_items', product_id=1)])
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    waiting = runtime.get_task(queued_db, USER, task.id)
    assert waiting.status == 'WAITING_INPUT'
    monkeypatch.delenv('CHEMICALOPS_EXECUTION_ID')
    monkeypatch.delenv('CHEMICALOPS_EXECUTION_TOKEN')
    runtime.schedule_async(queued_db, USER, BackgroundTasks(), runtime.prepare_chat_continue, task.id,
        runtime.TaskContinue(question='选择 RFQ-OWN，继续比较报价', revision=waiting.revision, rfq_item_id=11))
    queued_db.expire_all()
    memory = queued_db.get(AIAgentTask, task.id).payload['memory_state']
    assert memory['goal']['intent'] == ('inventory_and_quotes_query' if combined else 'supplier_quote_query')
    assert memory['pending'] is None
    execution = queued_db.scalar(select(TaskExecution).where(TaskExecution.business_id == task.id)
                                 .order_by(TaskExecution.run_generation.desc()))
    current = claim(queued_db, execution, monkeypatch)
    original_resume = runtime._resume_action
    calls = []
    def crash_after_product(state):
        calls.append(state.revision)
        if len(calls) == 2:
            raise KeyboardInterrupt('simulated process crash after selected product checkpoint')
        return original_resume(state)
    monkeypatch.setattr(runtime, '_resume_action', crash_after_product)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    execution = queued_db.get(TaskExecution, execution.id)
    assert execution.checkpoint['verified_product'] == 1
    service.finish(queued_db, execution.id, execution.fencing_token, status='FAILED', retryable=True)
    execution.next_attempt_at = None
    queued_db.commit()
    current = claim(queued_db, execution, monkeypatch)
    monkeypatch.setattr(runtime, '_resume_action', original_resume)
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    result = runtime.get_task(queued_db, USER, task.id)
    assert result.status == 'SUCCEEDED'
    assert [e.get('tool') for e in result.trace[2:-1]] == (
        ['catalog.search_products', 'inventory.query_available', 'supplier_quotes.find_rfq_items', 'supplier_quotes.compare'] if combined else
        ['catalog.search_products', 'supplier_quotes.find_rfq_items', 'supplier_quotes.compare'])
    assert len(model_script[1]) == 2  # 仅初次定位使用模型，选择与崩溃恢复均由服务端续跑。
    assert len(queued_db.scalars(select(AIMessage)).all()) == 4


def test_disabled_user_while_queued_never_calls_model(queued_db, model_script, monkeypatch):
    from sqlalchemy import text
    task, execution = accept(queued_db)
    queued_db.execute(text("UPDATE sys_users SET status='INACTIVE' WHERE id=7"))
    queued_db.commit()
    current = claim(queued_db, execution, monkeypatch)
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    row = queued_db.get(AIAgentTask, task.id)
    assert row.status == "FAILED" and row.error_code == "PERMISSION_DENIED"
    assert model_script[1] == []


@pytest.mark.parametrize("chat", [False, True])
def test_async_start_and_continue_api_remain_202(queued_db, model_script, monkeypatch, chat):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth import get_current_user
    from app.core.db import get_db
    from app.modules.ai.controller import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    allow_ai_workspace_permission(app)
    app.dependency_overrides[get_db] = lambda: queued_db
    app.dependency_overrides[get_current_user] = lambda: USER
    start_url = "/api/v1/ai/agent/chat/start" if chat else "/api/v1/ai/agent/tasks/start"
    with TestClient(app) as client:
        response = client.post(start_url, json={"question": "查询测试乙醇库存"})
        assert response.status_code == 202
        task = response.json()
        execution = queued_db.scalar(select(TaskExecution).where(TaskExecution.business_id == task["id"]))
        current = claim(queued_db, execution, monkeypatch)
        model_script[0].append({"action": "ask_user", "question": "请补充规格"})
        asyncio.run(runtime.run_prepared_task(task["id"], USER.id, current.business_revision))
        monkeypatch.delenv("CHEMICALOPS_EXECUTION_ID")
        monkeypatch.delenv("CHEMICALOPS_EXECUTION_TOKEN")
        waiting = runtime.get_task(queued_db, USER, task["id"])
        continue_url = (f"/api/v1/ai/agent/chat/{task['id']}/continue" if chat
                        else f"/api/v1/ai/agent/tasks/{task['id']}/continue/start")
        response = client.post(continue_url, json={"question": "测试乙醇", "revision": waiting.revision})
        assert response.status_code == 202 and response.json()["id"] == task["id"]
        assert response.json()["status"] == "RUNNING"


def test_transport_error_preserves_checkpoint_for_queue_retry(queued_db, monkeypatch):
    import httpx
    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError("simulated unavailable model")
    async def understand(*args, **kwargs):
        return runtime.routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"])
    monkeypatch.setattr(runtime.routing, "understand", understand)
    monkeypatch.setattr(runtime.llm, "chat", unavailable)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    assert queued_db.get(AIAgentTask, task.id).status == "RUNNING"
    assert len(queued_db.scalars(select(AIMessage)).all()) == 2


def test_token_budget_is_persisted_to_task_and_queue_checkpoint(queued_db, monkeypatch):
    from app.modules.ai import gateway

    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    async def understand(*args, **kwargs):
        return runtime.routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"])
    async def ask_user(*args, **kwargs):
        budget = gateway.current_task_token_budget()
        reservation = budget.reserve("planner prompt", 8)
        budget.settle(reservation, {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6})
        return SimpleNamespace(message=SimpleNamespace(content='{"action":"ask_user","question":"请补充信息"}'))
    monkeypatch.setattr(runtime.routing, "understand", understand)
    monkeypatch.setattr(runtime.llm, "chat", ask_user)

    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    saved_task = queued_db.get(AIAgentTask, task.id)
    saved_execution = queued_db.get(TaskExecution, execution.id)
    assert saved_task.status == "WAITING_INPUT"
    assert saved_task.payload["token_budget"]["calls"] == 1
    assert saved_task.payload["token_budget"]["used_tokens"] >= 6
    assert saved_task.payload["messages"] and saved_task.payload["trace"][-1]["action"] == "ask_user"
    assert saved_execution.checkpoint["token_budget"] == saved_task.payload["token_budget"]


def test_model_wait_cancel_rejects_late_reply(queued_db, monkeypatch):
    import json
    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    async def cancelled(*args, **kwargs):
        runtime.cancel_task(queued_db, USER, task.id)
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps({"action": "ask_user", "question": "late reply"})))
    monkeypatch.setattr(runtime.llm, "chat", cancelled)
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    assert queued_db.get(AIAgentTask, task.id).status == "CANCELLED"
    assert queued_db.get(TaskExecution, execution.id).status == "CANCELLED"
    assert queued_db.scalar(select(AIMessage).where(AIMessage.message_role == "ASSISTANT")).content == "任务已取消。"


def test_permissions_revoked_while_queued_fail_before_model(queued_db, monkeypatch, model_script):
    task, execution = accept(queued_db)
    current = claim(queued_db, execution, monkeypatch)
    monkeypatch.setattr(runtime.tools, "get_user_permission_codes", lambda _db, _id: [])
    asyncio.run(runtime.run_prepared_task(task.id, USER.id, current.business_revision))
    queued_db.expire_all()
    assert queued_db.get(AIAgentTask, task.id).error_code == "PERMISSION_DENIED"
    assert model_script[1] == []


def test_drained_queue_rolls_back_to_background_without_replaying_old_task(queued_db, monkeypatch):
    task, execution = accept(queued_db)
    runtime.cancel_task(queued_db, USER, task.id)
    old_settings = runtime.get_settings().model_copy(update={"agent_execution_mode": "in_process"})
    monkeypatch.setattr(runtime, "get_settings", lambda: old_settings)
    background = BackgroundTasks()
    new = runtime.schedule_async(queued_db, USER, background, runtime.prepare_chat_task,
                                runtime.ChatTaskCreate(question="新的测试库存查询"))
    assert new.id != task.id and len(background.tasks) == 1
    assert len(queued_db.scalars(select(TaskExecution)).all()) == 1
    assert service.claim_execution(queued_db, execution.id, 0, "old-message", 60) is None
