"""多意图计划与执行使用真实只读 SQL/工具；模型以结构化替身隔离。"""

import asyncio

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.modules.ai import multi_intent as multi, routing, service, text2sql
from app.modules.ai.model import AIConversationState
from app.modules.ai.task_status import BatchStatus, TaskStatus
from app.modules.system.model import User
from tests.test_agent_read_tools import tool_db
from tests.test_agent_runtime import USER
from tests.test_rbac_separation import as_demo_role


def decision(*tasks):
    """构造通过类别与依赖校验的批次理解，不调用真实模型。"""
    return routing.Understanding(purpose="query", tasks=list(dict.fromkeys(task["kind"] for task in tasks)), sub_tasks=tasks)


def product_task(id="t1", kind="inventory", **kwargs):
    """生成明确产品的原子只读任务，允许测试覆盖槽位或依赖。"""
    return {"id": id, "kind": kind, "question": "查测试乙醇" + ("库存" if kind == "inventory" else "报价"),
            "slots": {"product_keyword": "测试乙醇"}, **kwargs}


def test_same_category_multiple_tasks_and_dependency_validation():
    """同类指标保留多份计划，拒绝自依赖、前向依赖和被否定的子任务。"""
    result = decision({"id": "t1", "kind": "analytics", "question": "统计订单数量"},
                      {"id": "t2", "kind": "analytics", "question": "统计订单金额", "depends_on": ["t1"]})
    assert result.route == "batch" and len(result.tasks) == 1 and len(result.sub_tasks) == 2
    for bad in [["t2"], ["t1"]]:
        with pytest.raises(ValueError):
            decision({"id": "t1", "kind": "analytics", "question": "统计订单数量", "depends_on": bad})
    with pytest.raises(ValueError):
        routing.Understanding(purpose="query", tasks=["quotes"], excluded_tasks=["quotes"], sub_tasks=[product_task(kind="quotes")])


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
    from app.modules.ai.intent import Intent, IntentResult
    resolved = routing.Understanding(purpose="query", dialogue_action="modify", tasks=["analytics"],
        sub_tasks=[{"id": "t2", "kind": "analytics", "question": "统计已批准的采购申请数量"}])
    intent = IntentResult(Intent.QUERY, "semantic_route", resolved.model_dump(mode="json"))
    assert service._resolved_query_question("只修改第二项", intent) == "统计已批准的采购申请数量"
