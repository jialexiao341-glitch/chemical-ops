"""多意图计划与执行使用真实只读 SQL/工具；模型以结构化替身隔离。"""

import asyncio
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai import multi_intent as multi, routing, service, text2sql
from app.modules.ai.model import AIConversationState
from app.modules.ai.schema import BatchStatus, SubTask, TaskStatus
from app.modules.system.model import User
from tests.test_agent_read_tools import tool_db
from tests.test_agent_runtime import USER
from tests.test_rbac_separation import as_demo_role


def decision(*tasks):
    """构造批次理解；单项执行测试直接调用低层执行器，因此单项样本不经过路由校验。"""
    subtasks = [SubTask.model_validate(task) for task in tasks]
    values = {"purpose": "query", "execution_mode": "batch",
              "tasks": list(dict.fromkeys(task.kind for task in subtasks)), "sub_tasks": subtasks}
    if len(subtasks) < 2:
        return routing.Understanding.model_construct(**values)
    return routing.Understanding(**values)


def product_task(id="t1", kind="inventory", **kwargs):
    """生成明确产品的原子只读任务，允许测试覆盖槽位或依赖。"""
    return {"id": id, "kind": kind, "question": "查测试乙醇" + ("库存" if kind == "inventory" else "报价"),
            "slots": {"product_keyword": "测试乙醇"}, **kwargs}


def test_batch_public_entry_revalidates_the_execution_contract():
    from app.core.errors import BusinessValidationError

    valid = decision(product_task(), product_task("t2"))
    assert multi.validate_batch_decision(valid).route == "batch"

    invalid = routing.Understanding.model_construct(
        purpose="query", execution_mode="batch", tasks=["inventory"], sub_tasks=[
            routing.SubTask(id="t1", kind="inventory", question="查测试乙醇库存")])
    with pytest.raises(BusinessValidationError):
        multi.validate_batch_decision(invalid)

    agent = routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"])
    with pytest.raises(BusinessValidationError):
        multi.validate_batch_decision(agent)


def test_same_category_multiple_tasks_and_dependency_validation():
    """同类指标保留多份计划，拒绝自依赖、前向依赖和被否定的子任务。"""
    result = decision({"id": "t1", "kind": "analytics", "question": "统计订单数量"},
                      {"id": "t2", "kind": "analytics", "question": "统计订单金额", "depends_on": ["t1"]})
    assert result.route == "batch" and len(result.tasks) == 1 and len(result.sub_tasks) == 2
    for bad in [["t2"], ["t1"]]:
        with pytest.raises(ValueError):
            routing.Understanding(purpose="query", execution_mode="batch", tasks=["analytics"], sub_tasks=[
                {"id": "t1", "kind": "analytics", "question": "统计订单数量", "depends_on": bad},
                {"id": "t2", "kind": "analytics", "question": "统计订单金额"},
            ])
    with pytest.raises(ValueError):
        routing.Understanding(purpose="query", execution_mode="batch", tasks=["quotes"], excluded_tasks=["quotes"], sub_tasks=[product_task(kind="quotes")])


def test_inventory_quotes_share_product_lookup_and_have_separate_evidence(tool_db, monkeypatch):
    """同产品只定位一次，库存与报价分别取证且历史回放可重验。"""
    calls = []
    original = multi.agent_tools.execute_tool
    def execute(db, user, call):
        calls.append(call.tool)
        return original(db, user, call)
    monkeypatch.setattr(multi.agent_tools, "execute_tool", execute)
    batch = asyncio.run(multi.execute_batch(tool_db, USER,
        decision(product_task(), product_task("t2", "quotes", slots={"product_keyword": "测试乙醇", "rfq_no": "RFQ-OWN"})), Settings(_env_file=None)))
    assert batch.status == BatchStatus.SUCCEEDED
    assert calls.count("catalog.search_products") == 1
    assert [task.evidence[-1]["tool"] for task in batch.tasks] == ["inventory.query_available", "supplier_quotes.compare"]
    assert all(task.execution_plan for task in batch.tasks)
    assert "已完成 2/2" in multi.summarize(batch)
    assert multi.history_accessible(tool_db, USER, batch.model_dump(mode="json"))


def test_product_tool_uses_remaining_batch_deadline(tool_db, monkeypatch):
    from app.modules.ai.tool_sql_timeout import current_task_deadline

    observed = []

    def capture_deadline(_db, _user, _task, result, _products, **_kwargs):
        observed.append(current_task_deadline())
        result.status = TaskStatus.SUCCEEDED

    monkeypatch.setattr(multi, "execute_product_task", capture_deadline)
    before = monotonic()
    asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task()), Settings(_env_file=None)))

    assert observed[0] is not None and observed[0] > before


def test_tool_timeout_keeps_completed_results_and_runs_independent_items(tool_db, monkeypatch):
    from app.modules.ai.tool_sql_timeout import ToolExecutionTimeout

    original = multi.agent_tools.execute_tool
    calls = []

    def timeout_first_tool(db, user, call):
        calls.append(call.tool)
        if len(calls) == 1:
            raise ToolExecutionTimeout("database deadline elapsed")
        return original(db, user, call)

    monkeypatch.setattr(multi.agent_tools, "execute_tool", timeout_first_tool)
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        product_task("t1"), product_task("t2")), Settings(_env_file=None)))

    assert batch.tasks[0].status == TaskStatus.FAILED
    assert batch.tasks[0].error_code == "TOOL_TIMEOUT"
    assert batch.tasks[1].status == TaskStatus.SUCCEEDED
    assert batch.status == BatchStatus.PARTIAL


def test_batch_cancellation_waits_for_tool_thread_before_session_cleanup(tool_db, monkeypatch):
    started = Event()
    release = Event()

    def blocked_product_task(*_args, **_kwargs):
        started.set()
        release.wait(5)

    monkeypatch.setattr(multi, "execute_product_task", blocked_product_task)

    async def cancel_batch():
        task = asyncio.create_task(multi.execute_batch(
            tool_db, USER, decision(product_task()), Settings(_env_file=None)))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            was_done_before_worker_exit = task.done()
        finally:
            release.set()
        batch = await task
        return was_done_before_worker_exit, batch

    was_done, batch = asyncio.run(cancel_batch())
    assert was_done is False
    assert batch.tasks[0].status == TaskStatus.CANCELLED


def test_batch_inventory_accepts_exact_warehouse_code_with_visibility_scope(tool_db):
    from sqlalchemy import text
    tool_db.execute(text("UPDATE warehouses SET warehouse_code='WH-OWN' WHERE id=1"))
    tool_db.execute(text("UPDATE warehouses SET warehouse_code='WH-OTHER' WHERE id=2"))

    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        product_task(slots={"product_keyword": "测试乙醇", "warehouse_keyword": "WH-OWN"}),
    ), Settings(_env_file=None)))
    task = batch.tasks[0]
    assert task.status == TaskStatus.SUCCEEDED
    inventory_call = next(call for call in task.tool_calls if call["tool"] == "inventory.query_available")
    assert inventory_call["arguments"]["warehouse_id"] == 1

    hidden = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        product_task(slots={"product_keyword": "测试乙醇", "warehouse_keyword": "WH-OTHER"}),
    ), Settings(_env_file=None)))
    assert hidden.tasks[0].status == TaskStatus.WAITING_INPUT
    assert not any(call["tool"] == "inventory.query_available" for call in hidden.tasks[0].tool_calls)


def test_plan_failure_blocks_dependency_but_independent_inventory_continues(tool_db, monkeypatch):
    """计划失败只阻塞其依赖，不能阻止独立任务或伪装整批成功。"""
    async def rejected(*args, **kwargs):
        raise BusinessValidationError("不能访问")
    monkeypatch.setattr(multi, "plan_analytics", rejected)
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        {"id": "t1", "kind": "analytics", "question": "查订单金额"},
        product_task("t2", depends_on=["t1"]), product_task("t3")), Settings(_env_file=None)))
    assert batch.status == BatchStatus.PARTIAL
    assert [task.status for task in batch.tasks] == [TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.SUCCEEDED]
    assert batch.tasks[1].evidence == [] and "已完成 1/3" in multi.summarize(batch)


def test_missing_product_is_waiting_and_never_invented(tool_db):
    """缺少产品时等待补充，依赖项不执行，不能猜测对象 ID。"""
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        product_task(slots={}), product_task("t2", depends_on=["t1"])), Settings(_env_file=None)))
    assert batch.status == BatchStatus.WAITING_INPUT
    assert [task.status for task in batch.tasks] == [TaskStatus.WAITING_INPUT, TaskStatus.BLOCKED]
    assert all(not task.evidence for task in batch.tasks)


@pytest.mark.parametrize("task_kind", ["inventory", "quotes"])
@pytest.mark.parametrize("unsupported_slots", [
    {"date_from": "2026-10-01"},
    {"unit": "升"},
])
def test_batch_uses_shared_prompt_for_unsupported_product_slots(tool_db, task_kind, unsupported_slots):
    from app.modules.ai.product_query_policy import unsupported_product_slot_prompt

    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(
        product_task(kind=task_kind, slots={"product_keyword": "测试乙醇", **unsupported_slots}),
    ), Settings(_env_file=None)))
    task = batch.tasks[0]

    assert task.status == TaskStatus.WAITING_INPUT
    assert task.answer == unsupported_product_slot_prompt(tuple(unsupported_slots))
    assert task.tool_calls == []


def test_inventory_sums_all_matching_specifications_and_rechecks_history(tool_db):
    from sqlalchemy import text
    tool_db.execute(text("INSERT INTO md_products VALUES (3, '测试乙醇', 'ACTIVE', 'P-ETH-2', '工业级', '200kg', 1, 1)"))
    tool_db.execute(text("INSERT INTO inventory_balances VALUES (6, 1, 2, 3, 1, 'AVAILABLE', 40, 10)"))
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task()), Settings(_env_file=None)))
    task = batch.tasks[0]
    assert task.status == TaskStatus.SUCCEEDED
    assert "110 千克" in task.answer and "5 升" in task.answer and "2 个规格" in task.answer
    assert [call['arguments']['product_id'] for call in task.tool_calls if call['tool']=='inventory.query_available'] == [1, 3]
    assert multi.history_accessible(tool_db, USER, batch.model_dump(mode='json'))
    tool_db.execute(text("UPDATE warehouses SET manager_id=8 WHERE id=1"))
    assert not multi.history_accessible(tool_db, USER, batch.model_dump(mode='json'))


def test_similar_names_require_real_chemical_identity(tool_db):
    from sqlalchemy import text
    tool_db.execute(text("INSERT INTO md_products (id,product_name,status,product_code,unit_id,chemical_id) VALUES (3,'其他测试乙醇衍生品','ACTIVE','P-OTHER',1,2)"))
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task()), Settings(_env_file=None)))
    assert batch.tasks[0].status == TaskStatus.WAITING_INPUT
    assert not any(call['tool']=='inventory.query_available' for call in batch.tasks[0].tool_calls)
    tool_db.execute(text("UPDATE md_products SET chemical_id=1 WHERE id IN (1,3)"))
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task()), Settings(_env_file=None)))
    assert batch.tasks[0].status == TaskStatus.SUCCEEDED


def test_single_inventory_reply_keeps_evidence_and_requested_advice(tool_db):
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task()), Settings(_env_file=None)))
    answer = multi.summarize(batch, '查测试乙醇库存')
    assert answer == batch.tasks[0].answer
    assert '80 千克' in answer and '5 升' in answer
    assert '当前授权' not in answer and '余额状态口径' not in answer
    inventory = next(value for value in batch.tasks[0].evidence if value.get('tool') == 'inventory.query_available')
    assert inventory['scope'] and inventory['warnings'] and inventory['sources']
    assert '安全库存' in multi.summarize(batch, '查测试乙醇库存，有什么建议？')


def test_inventory_comparison_and_advice_use_actual_totals_without_unit_conversion(tool_db):
    from sqlalchemy import text
    tool_db.execute(text("INSERT INTO md_products VALUES (3,'测试甲醇','ACTIVE','P-METH',NULL,NULL,1,1)"))
    tool_db.execute(text("INSERT INTO inventory_balances VALUES (6,1,2,3,1,'AVAILABLE',50,0)"))
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task(),
        product_task('t2', slots={'product_keyword':'测试甲醇'}, question='查询测试甲醇库存')), Settings(_env_file=None)))
    answer = multi.summarize(batch, '乙醇和甲醇哪个多？需要什么行动？')
    assert '80 千克；测试甲醇 50 千克' in answer and '按数量从多到少' in answer
    assert '其他单位' in answer and '安全库存' in answer and '未创建或执行' in answer
    assert '### 2.' in answer


@pytest.mark.parametrize("stream", [False, True])
def test_api_multiple_query_plans_execute_persist_and_reload(client, db_session, monkeypatch, stream):
    """同步/流式共用批次执行，真实 SQL 保存两份计划，并以单次路由凭据复用。"""
    understand_calls = []
    route = decision({"id": "t1", "kind": "analytics", "question": "统计采购订单数量"},
                     {"id": "t2", "kind": "analytics", "question": "统计采购申请数量"})
    async def understand(*args, **kwargs):
        understand_calls.append(True)
        return route
    plans = []
    async def plan(db, user, task, settings, **kwargs):
        query = text2sql.QueryPlan(dataset="purchase_orders" if task.id == "t1" else "purchase_requests", metric="count")
        plans.append(query)
        return query
    async def no_rewrite(*args):
        return None
    monkeypatch.setattr(routing, "understand", understand)
    monkeypatch.setattr(multi, "plan_analytics", plan)
    monkeypatch.setattr(service, "_rewrite_text2sql_answer", no_rewrite)
    with as_demo_role(db_session, "BUYER"):
        ticket = client.post("/api/v1/ai/route", json={"question": "统计采购订单和采购申请数量"}).json()
        assert ticket["route"] == "batch"
        response = client.post("/api/v1/ai/chat" + ("/stream" if stream else ""), json={
            "messages": [{"role": "user", "content": "统计采购订单和采购申请数量"}], "route_token": ticket["route_token"]})
        assert response.status_code == 200
        if stream:
            import json
            payload = next(json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and '"batch_result"' in line)
            events = [frame.split('\ndata: ', 1) for frame in response.text.strip().split('\n\n')]
            deltas = [json.loads(value)['content'] for event, value in events if event == 'event: delta']
            assert len(deltas) > 1 and ''.join(deltas) == payload['answer']
            progress = [json.loads(value) for event, value in events if event == 'event: progress']
            assert progress and all(set(task) == {'id', 'kind', 'question', 'status'} for snapshot in progress for task in snapshot['tasks'])
            assert events[-1][0] == 'event: done'
        else:
            payload = response.json()
        batch = payload["batch_result"]
        assert batch["status"] == "SUCCEEDED" and len(plans) == 2
        assert [task["query_plan"]["dataset"] for task in batch["tasks"]] == ["purchase_orders", "purchase_requests"]
        assert len(understand_calls) == 1  # 已签发的路由结果不会再调用模型。
        state = db_session.scalar(select(AIConversationState).where(AIConversationState.conversation_id == payload["conversation_id"]))
        assert state.query_plan is None and len(state.memory_state["batch_tasks"]) == 2
        history = client.get(f"/api/v1/ai/conversations/{payload['conversation_id']}/messages").json()
        assert "已完成 2/2" in history["items"][-1]["content"]


def test_generate_two_plans_before_execution_with_real_planner_parser(db_session, monkeypatch):
    """走真实计划解析与鉴权，确认全部独立计划生成后才执行第一项。"""
    import json
    from types import SimpleNamespace
    events = []
    async def model(*args, **kwargs):
        assert json.loads(args[0].messages[0].content)["question"]
        assert "# 角色与任务" in kwargs["system_prompt"]
        events.append("plan")
        dataset = "purchase_orders" if events.count("plan") == 1 else "purchase_requests"
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps({"dataset": dataset, "metric": "count"})))
    original = service._run_text2sql_for_chat
    async def execute(*args, **kwargs):
        events.append("execute")
        return await original(*args, **kwargs)
    async def no_rewrite(*args):
        return None
    monkeypatch.setattr(text2sql, "chat", model)
    monkeypatch.setattr(service, "_run_text2sql_for_chat", execute)
    monkeypatch.setattr(service, "_rewrite_text2sql_answer", no_rewrite)
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    batch = asyncio.run(multi.execute_batch(db_session, user, decision(
        {"id": "t1", "kind": "analytics", "question": "统计采购订单数量"},
        {"id": "t2", "kind": "analytics", "question": "统计采购申请数量"}), Settings(_env_file=None)))
    assert batch.status == BatchStatus.SUCCEEDED and events == ["plan", "plan", "execute", "execute"]


def test_history_rechecks_current_warehouse_scope(tool_db):
    """仓库归属变更后旧批次不得继续返回库存答案或来源。"""
    from sqlalchemy import text
    batch = asyncio.run(multi.execute_batch(tool_db, USER, decision(product_task(), product_task("t2")), Settings(_env_file=None)))
    assert multi.history_accessible(tool_db, USER, batch.model_dump(mode="json"))
    tool_db.execute(text("UPDATE warehouses SET manager_id=8 WHERE id=1"))
    assert not multi.history_accessible(tool_db, USER, batch.model_dump(mode="json"))


def test_dependent_plan_receives_only_successful_predecessor_evidence(db_session, monkeypatch):
    """依赖计划在前项执行后生成，接收真实前项证据，保留独立计划。"""
    received = []
    async def plan(db, user, task, settings, **kwargs):
        received.append((task.id, kwargs.get("dependencies")))
        return text2sql.QueryPlan(dataset="purchase_orders", metric="count")
    async def no_rewrite(*args):
        return None
    monkeypatch.setattr(multi, "plan_analytics", plan)
    monkeypatch.setattr(service, "_rewrite_text2sql_answer", no_rewrite)
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    batch = asyncio.run(multi.execute_batch(db_session, user, decision(
        {"id": "t1", "kind": "analytics", "question": "统计订单数量"},
        {"id": "t2", "kind": "analytics", "question": "查询前项对象的订单数量", "depends_on": ["t1"]}), Settings(_env_file=None)))
    assert batch.status == BatchStatus.SUCCEEDED
    assert received[0] == ("t1", None)
    assert received[1][1][0]["evidence"] == batch.tasks[0].evidence


def test_single_followup_uses_resolved_subtask_question():
    """理解器还原的第二项查询必须传给规划器，不能丢失为无上下文的原句。"""
    from app.modules.ai.schema import Intent, IntentResult
    resolved = routing.Understanding(purpose="query", execution_mode="query", dialogue_action="modify", tasks=["analytics"],
        sub_tasks=[{"id": "t2", "kind": "analytics", "question": "统计已批准的采购申请数量"}])
    intent = IntentResult(Intent.QUERY, "semantic_route", resolved.model_dump(mode="json"))
    assert service._resolved_query_question("只修改第二项", intent) == "统计已批准的采购申请数量"
