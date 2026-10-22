"""隔离业务库与脚本化模型验证 Agent 多步任务；不代表真实模型成功率。"""

import asyncio
import json
from threading import get_ident
from time import sleep
from types import SimpleNamespace

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai import agent_runtime as runtime, agent_tools as tools
from app.modules.ai.controller import router
from app.modules.ai.model import AIAgentTask, AIConversationState, AIMessage, AIConversation
from app.modules.products.model import Product
from tests.conftest import login
from tests.test_agent_read_tools import allow_ai_workspace_permission, tool_db


USER = SimpleNamespace(id=7)


@pytest.fixture
def task_db(tool_db, monkeypatch):
    """复用真实 SQL 的隔离业务样本，额外建立任务表和有限预算配置。"""
    AIAgentTask.__table__.create(tool_db.bind)
    monkeypatch.setattr(runtime, "get_settings", lambda: Settings(_env_file=None, agent_execution_mode="in_process", openai_api_key="test-key"))
    return tool_db


@pytest.fixture
def model_script(monkeypatch):
    """仅替换外部模型 HTTP 调用；动作校验、Graph、数据库和权限仍执行真实代码。"""
    actions, contexts = [], []
    async def chat(request, settings, *, response_format, system_prompt, interpret_only=False):
        """按预期动作响应并保留模型收到的上下文，验证工具结果确实反馈给下一步。"""
        if system_prompt.startswith(runtime.routing.ROUTING_PROMPT):
            assert response_format["type"] == "json_schema"
            # 脚本模型仅隔离执行链；真实语义效果由独立评测验证。
            payload = json.loads(request.messages[0].content)
            question = payload['question']
            switching = question.startswith('改查')
            previous = '' if switching else payload.get('context', {}).get('memory', {}).get('goal', {}).get('intent', '')
            inventory = '库存' in question or 'inventory' in previous
            quotes = '报价' in question or '询价' in question or 'quotes' in previous or 'quote' in previous
            tasks = (['inventory'] if inventory else []) + (['quotes'] if quotes else [])
            aggregate_products = '汇总' in question and '全部规格' in question
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                'purpose': 'query', 'execution_mode': 'agent', 'tasks': tasks or ['inventory'],
                'dialogue_action': 'switch' if switching else 'continue',
                'slots': {'aggregate_products': aggregate_products},
            })))
        assert response_format == {"type": "json_object"}
        assert system_prompt == runtime.PLANNER_PROMPT and settings.llm_max_tokens <= 2048
        contexts.append(json.loads(request.messages[0].content))
        action = actions.pop(0)
        content = action if isinstance(action, str) else json.dumps(action, ensure_ascii=False)
        return SimpleNamespace(message=SimpleNamespace(content=content))
    monkeypatch.setattr(runtime.llm, "chat", chat)
    return actions, contexts


def tool(name, **arguments):
    """构造模型动作，与服务端工具参数保持分离。"""
    return {"action": "call_tool", "tool": name, "arguments": arguments}


def _large_inventory_entry(count: int = 100) -> dict:
    rows = [
        {"balance_id": index, "warehouse_id": 1, "warehouse_name": "测试仓库",
         "batch_id": 1, "batch_no": f"B-{index:03d}", "expiry_date": None,
         "unit_id": 1, "unit_name": "千克", "status": "AVAILABLE",
         "quantity": "10.000000", "locked_quantity": "0.000000",
         "available_quantity": "10.000000"}
        for index in range(1, count + 1)
    ]
    return {
        "step": 1, "action": "call_tool", "tool": "inventory.query_available",
        "arguments": {"product_id": 1, "limit": count}, "status": "SUCCEEDED",
        "result": {
            "tool": "inventory.query_available", "product_id": 1, "product_name": "测试乙醇",
            "warehouse_id": None, "scope": "测试范围", "total_rows": count, "truncated": False,
            "totals": [{"unit_id": 1, "unit_name": "千克", "available_quantity": f"{count * 10}.000000"}],
            "rows": rows, "sources": [{"resource": "inventory_balances", "record_id": index}
                                      for index in range(1, count + 1)], "warnings": [],
        },
    }


def test_planner_view_compacts_large_results_without_mutating_evidence():
    entry = _large_inventory_entry()
    compact = runtime._planner_view(entry)

    assert len(compact["result"]["rows"]) == runtime.PLANNER_RESULT_ROW_LIMIT
    assert len(compact["result"]["sources"]) == runtime.PLANNER_RESULT_ROW_LIMIT
    assert compact["result"]["total_rows"] == 100
    assert compact["result"]["planner_truncated"] is True
    assert "完整结果已保存在任务证据中" in compact["result"]["planner_note"]
    # 规划视图只是拷贝；完成摘要/历史证据仍读取原始轨迹。
    assert len(entry["result"]["rows"]) == 100
    assert "planner_truncated" not in entry["result"]


def test_agent_resolves_exact_warehouse_code_with_access_scope(task_db):
    task_db.execute(text("UPDATE warehouses SET warehouse_code='WH-OWN' WHERE id=1"))

    assert runtime._resolve_agent_warehouse(task_db, USER, "WH-OWN") == 1
    with pytest.raises(BusinessValidationError, match="准确名称或编码"):
        runtime._resolve_agent_warehouse(task_db, USER, "WH-OTHER")


def test_planner_view_limits_sources_even_when_rows_are_small():
    entry = _large_inventory_entry(count=1)
    entry["result"]["sources"] = [{"resource": "inventory_balances", "record_id": index}
                                   for index in range(100)]

    compact = runtime._planner_view(entry)

    assert len(compact["result"]["rows"]) == 1
    assert len(compact["result"]["sources"]) == runtime.PLANNER_RESULT_ROW_LIMIT
    assert compact["result"]["planner_sources_truncated"] is True
    assert len(entry["result"]["sources"]) == 100


def test_planner_context_budget_keeps_goal_question_and_step_evidence():
    payload = {
        "messages": ["旧问题" + "x" * 6000 for _ in range(5)] + ["查询本轮目标乙醇库存"],
        "tools": [{"name": "inventory.query_available", "description": "只读查询库存"}],
        "current_turn_steps": [
            {"step": index, "action": "call_tool", "tool": "inventory.query_available",
             "status": "SUCCEEDED", "arguments": {"product_id": index},
             "result": {"product_id": index, "product_name": "测试乙醇", "total_rows": 100,
                        "truncated": False, "totals": [{"unit_id": 1, "unit_name": "千克",
                                                            "available_quantity": "100.000000"}],
                        "rows": [{"batch_no": "B-" + "x" * 3000} for _ in range(10)],
                        "sources": [{"record_id": source} for source in range(100)],
                        "debug_payload": "z" * 12000}}
            for index in range(1, 5)
        ],
        "recent_task_memory": {
            "goal": {"intent": "inventory_query", "description": "查询测试乙醇库存"},
            "recent_context": [{"role": "assistant", "text": "历史" + "y" * 5000} for _ in range(8)],
        },
        "workflow": {"pending": None, "all_products": False},
        "verified_product_id": 1,
    }
    original = json.loads(json.dumps(payload, ensure_ascii=False))

    context = runtime._fit_planner_context(payload, 6000)
    decoded = json.loads(context)

    assert len(context) <= 6000
    assert decoded["messages"][-1] == "查询本轮目标乙醇库存"
    assert decoded["recent_task_memory"]["goal"]["intent"] == "inventory_query"
    assert [step["step"] for step in decoded["current_turn_steps"]] == [1, 2, 3, 4]
    assert all(step["result"]["totals"][0]["available_quantity"] == "100.000000"
               for step in decoded["current_turn_steps"])
    assert payload == original


def test_planner_context_budget_fails_safely_when_mandatory_context_cannot_fit():
    payload = {"messages": ["查询库存"], "tools": [], "current_turn_steps": [],
               "recent_task_memory": {"goal": {"intent": "inventory_query"}}, "workflow": {}}

    with pytest.raises(BusinessValidationError, match="CONTEXT_LIMIT"):
        runtime._fit_planner_context(payload, 10)


def test_planner_context_uses_compacted_tool_view(monkeypatch):
    captured = []

    async def fake_chat(request, settings, **kwargs):
        captured.append(json.loads(request.messages[0].content))
        return SimpleNamespace(message=SimpleNamespace(content='{"action":"finish","evidence_steps":[1]}'))

    monkeypatch.setattr(runtime.llm, "chat", fake_chat)
    state = runtime.RunState(
        task_id="planner-view",
        revision=0,
        messages=["查询全部库存明细"],
        trace=[_large_inventory_entry()],
        turn_start=0,
        memory_state={"goal": {"intent": "inventory_query"}},
        workflow=runtime.Workflow(),
    )
    action = asyncio.run(runtime._decide(state, [], Settings(_env_file=None, openai_api_key="test")))
    assert action.action == "finish"
    context = captured[0]
    assert len(context["current_turn_steps"][0]["result"]["rows"]) == runtime.PLANNER_RESULT_ROW_LIMIT
    assert context["current_turn_steps"][0]["result"]["total_rows"] == 100


def test_decide_completes_large_multiturn_context_within_configured_budget(monkeypatch):
    captured = []

    async def fake_chat(request, settings, **kwargs):
        captured.append(request.messages[0].content)
        return SimpleNamespace(message=SimpleNamespace(content='{"action":"finish","evidence_steps":[1]}'))

    monkeypatch.setattr(runtime.llm, "chat", fake_chat)
    state = runtime.RunState(
        task_id="planner-budget", revision=0,
        messages=["历史问题" + "x" * 2000 for _ in range(5)] + ["查询测试乙醇库存"],
        trace=[_large_inventory_entry()], turn_start=0,
        memory_state={
            "goal": {"intent": "inventory_query", "description": "查询测试乙醇库存"},
            "recent_context": [{"role": "assistant", "text": "历史答复" + "y" * 2000} for _ in range(8)],
        },
        workflow=runtime.Workflow(),
    )
    settings = Settings(_env_file=None, openai_api_key="test", agent_context_max_chars=6000)

    action = asyncio.run(runtime._decide(state, [], settings))

    assert action.action == "finish"
    assert len(captured) == 1 and len(captured[0]) <= settings.agent_context_max_chars
    context = json.loads(captured[0])
    assert context["messages"][-1] == "查询测试乙醇库存"
    assert context["current_turn_steps"][0]["result"]["total_rows"] == 100
    assert context["current_turn_steps"][0]["result"]["totals"][0]["available_quantity"] == "1000.000000"


def test_planner_schema_correction_is_fitted_again_within_budget(monkeypatch):
    captured = []
    responses = ["not json", '{"action":"finish","evidence_steps":[1]}']

    async def fake_chat(request, settings, **kwargs):
        captured.append(request.messages[0].content)
        return SimpleNamespace(message=SimpleNamespace(content=responses.pop(0)))

    monkeypatch.setattr(runtime.llm, "chat", fake_chat)
    state = runtime.RunState(
        task_id="planner-correction-budget", revision=0,
        messages=["历史问题" + "x" * 2000 for _ in range(5)] + ["查询测试乙醇库存"],
        trace=[_large_inventory_entry()], turn_start=0,
        memory_state={"goal": {"intent": "inventory_query", "description": "查询测试乙醇库存"}},
        workflow=runtime.Workflow(),
    )
    settings = Settings(_env_file=None, openai_api_key="test", agent_context_max_chars=6000)

    action = asyncio.run(runtime._decide(state, [], settings))

    assert action.action == "finish"
    assert len(captured) == 2
    assert all(len(context) <= settings.agent_context_max_chars for context in captured)
    assert "format_correction" in json.loads(captured[1])


def start(db, question="查询测试乙醇库存"):
    """通过公开服务入口启动任务，便于核验最终数据库记录。"""
    return asyncio.run(runtime.create_task(db, USER, runtime.TaskCreate(question=question)))


def full_script(actions):
    """完整只读任务：定位产品、库存、定位询价、报价、引用两项证据完成。"""
    actions.extend([tool("catalog.search_products", keyword="测试乙醇"),
        tool("inventory.query_available", product_id=1),
        tool("supplier_quotes.find_rfq_items", product_id=1),
        tool("supplier_quotes.compare", product_id=1, rfq_item_id=11),
        {"action": "finish", "evidence_steps": [2, 4]}])


def test_full_goal_drives_four_tools_with_evidence_and_persisted_trace(task_db, model_script):
    """C19：模型动作串联业务工具，后续上下文含前一步真实结果，最终数值来自证据。"""
    actions, contexts = model_script
    full_script(actions)
    result = start(task_db, '查询测试乙醇库存并比较报价')
    assert result.status == 'SUCCEEDED' and result.revision == 5
    assert len(contexts) == 5 and not actions
    assert contexts[1]['current_turn_steps'][0]['result']['rows'][0]['product_id'] == 1
    assert contexts[2]['current_turn_steps'][1]['result']['totals'][0]['available_quantity'] == '80.000000'
    assert '80 千克' in result.reply and '8.000000 CNY/千克' in result.reply
    assert runtime.get_task(task_db, USER, result.id).trace == result.trace
    assert result.trace[-1]['evidence_steps'] == [2, 4]


@pytest.mark.parametrize(("timeout_error", "expected_code"), [
    ("tool", "TOOL_TIMEOUT"), ("unsupported", "TOOL_TIMEOUT_UNSUPPORTED"),
])
def test_tool_timeout_fails_task_without_replanning(task_db, model_script, monkeypatch, timeout_error, expected_code):
    from app.modules.ai.tool_sql_timeout import ToolExecutionTimeout, ToolTimeoutUnsupported

    actions, contexts = model_script
    actions.append(tool("catalog.search_products", keyword="测试乙醇"))
    calls = []

    def timeout_tool(*_args, **_kwargs):
        calls.append(True)
        error = ToolExecutionTimeout if timeout_error == "tool" else ToolTimeoutUnsupported
        raise error("database deadline elapsed")

    monkeypatch.setattr(runtime.tools, "execute_tool", timeout_tool)
    result = start(task_db)

    tool_entries = [entry for entry in result.trace if entry.get("action") == "call_tool"]
    assert result.status == "FAILED" and result.error_code == expected_code
    assert len(calls) == 1 and len(contexts) == 1
    assert tool_entries[-1]["error_code"] == expected_code


def test_invalid_tool_arguments_keep_existing_error_mapping(task_db, model_script):
    actions, _contexts = model_script
    actions.extend([
        tool("catalog.search_products", keyword=""),
        {"action": "ask_user", "question": "请补充有效的产品名称。"},
    ])

    result = start(task_db)
    tool_entries = [entry for entry in result.trace if entry.get("action") == "call_tool"]

    assert result.status == "WAITING_INPUT"
    assert tool_entries[0]["error_code"] == "INVALID_TOOL_REQUEST"


@pytest.mark.parametrize("task_kind", ["inventory", "quotes"])
@pytest.mark.parametrize("unsupported_slots", [
    {"date_from": "2026-10-01"},
    {"unit": "升"},
])
def test_agent_waits_before_tools_for_unsupported_product_slots(task_db, model_script, monkeypatch, task_kind, unsupported_slots):
    from app.modules.ai.product_query_policy import unsupported_product_slot_prompt

    actions, _ = model_script
    actions.extend([
        tool('catalog.search_products', keyword='测试乙醇'),
        tool('inventory.query_available', product_id=1),
        {'action': 'finish', 'evidence_steps': [2]},
    ])
    question = "查询测试乙醇库存"
    decision = runtime.routing.Understanding(
        purpose="query", execution_mode="agent", tasks=[task_kind],
        slots={"product_keyword": "测试乙醇", **unsupported_slots},
    )
    route_token = runtime.routing.issue_ticket(decision, USER.id, question, None)
    calls = []
    execute_tool = runtime.tools.execute_tool

    def record_tool_call(db, user, call):
        calls.append(call.tool)
        return execute_tool(db, user, call)

    monkeypatch.setattr(runtime.tools, "execute_tool", record_tool_call)
    result = asyncio.run(runtime.create_task(
        task_db, USER, runtime.TaskCreate(question=question, route_token=route_token)
    ))

    assert result.status == "WAITING_INPUT", result.model_dump()
    assert result.reply == unsupported_product_slot_prompt(tuple(unsupported_slots))
    assert calls == []


def test_agent_sync_tool_runs_off_event_loop_and_keeps_heartbeat_responsive(task_db, model_script, monkeypatch):
    actions, _ = model_script
    actions.extend([
        tool("catalog.search_products", keyword="测试乙醇"),
        tool("inventory.query_available", product_id=1),
        {"action": "finish", "evidence_steps": [2]},
    ])
    question = "查询测试乙醇库存"
    decision = runtime.routing.Understanding(
        purpose="query", execution_mode="agent", tasks=["inventory"],
        slots={"product_keyword": "测试乙醇"},
    )
    route_token = runtime.routing.issue_ticket(decision, USER.id, question, None)
    main_thread = get_ident()
    database_threads = []
    execute_tool = runtime.tools.execute_tool

    def slow_execute_tool(db, user, call):
        database_threads.append(get_ident())
        sleep(0.12)
        return execute_tool(db, user, call)

    monkeypatch.setattr(runtime.tools, "execute_tool", slow_execute_tool)

    async def run_with_heartbeat():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while not task.done():
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(runtime.create_task(
            task_db, USER, runtime.TaskCreate(question=question, route_token=route_token)
        ))
        monitor = asyncio.create_task(heartbeat())
        result = await task
        await monitor
        return result, ticks

    result, ticks = asyncio.run(run_with_heartbeat())

    assert result.status == "SUCCEEDED"
    assert database_threads and all(thread_id != main_thread for thread_id in database_threads)
    assert ticks >= 10


def test_multiple_products_pause_and_selected_candidate_continues(task_db, model_script):
    """C18：多规格结果强制暂停；选择有效候选后重新查询并继续库存工具。"""
    task_db.execute(text("INSERT INTO md_products VALUES (3, '测试乙醇工业级', 'ACTIVE', 'P-ETH-2', '工业级', '桶', 1, 2)"))
    task_db.commit()
    actions, _ = model_script
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    result = start(task_db, '查询测试乙醇库存')
    assert result.status == 'WAITING_INPUT'
    assert len(result.trace[0]['result']['rows']) == 2
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
        tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [3]}])
    continued = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='选择分析纯', revision=result.revision, product_id=1)))
    assert continued.status == 'SUCCEEDED' and continued.trace[2]['tool'] == 'inventory.query_available'


def test_inventory_summary_queries_all_specs_and_keeps_units_separate(task_db, model_script):
    task_db.execute(text("INSERT INTO md_products VALUES (3, '测试乙醇', 'ACTIVE', 'P-ETH-2', '工业级', '桶', 1, 1)"))
    task_db.execute(text("INSERT INTO inventory_balances VALUES (6, 1, 1, 3, 1, 'AVAILABLE', 7.25, 0)"))
    task_db.commit()
    actions, _ = model_script
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    result = start(task_db, '汇总查看测试乙醇全部规格库存')
    assert result.status == 'SUCCEEDED'
    inventory = [e['result'] for e in result.trace if e.get('tool') == 'inventory.query_available']
    assert {row['product_id'] for row in inventory} == {1, 3}
    assert '87.25 千克' in result.reply and '5 升' in result.reply
    assert '查到这 2 个规格的可用库存合计为' in result.reply


@pytest.mark.parametrize(
    "question,aggregate_products,expected_aggregate",
    [
        ("不要全部，只查分析纯库存", False, True),
        ("查乙醇库存", True, True),
    ],
)
def test_candidate_aggregation_uses_structured_understanding_slot(
    monkeypatch, question, aggregate_products, expected_aggregate
):
    from app.modules.ai.schema import Workflow

    monkeypatch.setattr("app.modules.ai.candidate_resolution.inventory_family", lambda *_args: True)
    state = runtime.RunState(
        task_id="test",
        revision=0,
        messages=[question],
        trace=[{"tool": "catalog.search_products", "arguments": {"keyword": "乙醇"}}],
        turn_start=0,
        memory_state={
            "goal": {"intent": "inventory_query", "description": question},
            "understanding": {"slots": {"aggregate_products": aggregate_products}},
        },
        workflow=Workflow(),
    )
    result = {
        "tool": "catalog.search_products",
        "rows": [{"product_id": 1}, {"product_id": 2}],
        "total_rows": 2,
        "truncated": False,
        "keyword": "乙醇",
    }

    runtime._resolve_candidates(state, result, object())

    assert state.workflow.all_products is expected_aggregate
    assert (state.workflow.pending is None) is expected_aggregate


def test_select_all_rechecks_candidates_and_queries_each_spec(task_db, model_script):
    task_db.execute(text("INSERT INTO md_products VALUES (3, '测试乙醇工业级', 'ACTIVE', 'P-ETH-2', '工业级', '桶', 1, 2)"))
    task_db.commit()
    actions, _ = model_script
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    result = start(task_db)
    assert result.status == 'WAITING_INPUT' and result.can_select_all_products
    # 自动续跑重新定位；已停用候选不再查询。
    task_db.execute(text("UPDATE md_products SET status='INACTIVE' WHERE id=3"))
    task_db.commit()
    continued = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='全选全部规格库存', revision=result.revision, all_products=True)))
    assert continued.status == 'SUCCEEDED'
    assert [e['result']['product_id'] for e in continued.trace if e.get('tool') == 'inventory.query_available'] == [1]


def test_select_all_without_pending_candidates_is_rejected(task_db, model_script):
    actions, _ = model_script
    actions.append({'action': 'ask_user', 'question': '需要查询哪个产品？'})
    result = start(task_db)
    with pytest.raises(BusinessValidationError, match='全选'):
        asyncio.run(runtime.continue_task(task_db, USER, result.id,
            runtime.TaskContinue(question='全选', revision=result.revision, all_products=True)))


def test_multiple_rfqs_pause_and_keep_confirmed_product_on_continue(task_db, model_script):
    """多询价选择继续时保留产品上下文，但仍重新验证产品和询价范围。"""
    task_db.execute(text("INSERT INTO rfqs VALUES (4, 'RFQ-OWN-2', 7, 'SENT')"))
    task_db.execute(text("INSERT INTO rfq_items VALUES (41, 4, 1, '工业级', NULL)"))
    task_db.commit()
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'), tool('supplier_quotes.find_rfq_items', product_id=1)])
    result = start(task_db, '查询测试乙醇报价')
    assert result.status == 'WAITING_INPUT'
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
        tool('supplier_quotes.find_rfq_items', product_id=1),
        tool('supplier_quotes.compare', product_id=1, rfq_item_id=11), {'action': 'finish', 'evidence_steps': [5]}])
    result = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='选择 RFQ-OWN', revision=result.revision, rfq_item_id=11)))
    assert result.status == 'SUCCEEDED'


def test_missing_name_asks_user_then_uses_new_input(task_db, model_script):
    """缺产品名称可由模型追问；用户补充后新上下文包含追加输入。"""
    actions, contexts = model_script
    actions.append({'action': 'ask_user', 'question': '需要查询哪个产品和规格？'})
    result = start(task_db, '帮我查库存')
    assert result.status == 'WAITING_INPUT'
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
        tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [3]}])
    result = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='测试乙醇分析纯', revision=result.revision)))
    assert result.status == 'SUCCEEDED'
    assert contexts[1]['messages'][-1] == '测试乙醇分析纯'


def test_client_cannot_select_fabricated_id_or_continue_stale_revision(task_db, model_script):
    """客户端选择只能来自历史候选；重复继续的过期版本被拒绝。"""
    actions, _ = model_script
    actions.append({'action': 'ask_user', 'question': '需要查询哪个产品？'})
    result = start(task_db)
    with pytest.raises(BusinessValidationError, match='候选'):
        asyncio.run(runtime.continue_task(task_db, USER, result.id,
            runtime.TaskContinue(question='选择', revision=result.revision, product_id=999)))
    with pytest.raises(DuplicateResourceError):
        asyncio.run(runtime.continue_task(task_db, USER, result.id,
            runtime.TaskContinue(question='选择', revision=0)))


@pytest.mark.parametrize('action,code', [
    ('not json', 'MODEL_FORMAT_ERROR'),
    ({'action': 'finish', 'evidence_steps': [999]}, 'INVALID_EVIDENCE'),
    ({'action': 'call_tool', 'tool': 'inventory.query_available', 'arguments': {'product_id': 1}, 'user_id': 9}, 'MODEL_FORMAT_ERROR'),
])
def test_invalid_model_output_and_unbacked_answer_stop(task_db, model_script, action, code):
    """格式无效、伪造证据或身份字段不能进入工具或最终回答。"""
    model_script[0].extend([action] * (2 if code == 'MODEL_FORMAT_ERROR' else 1))
    result = start(task_db)
    assert result.status == 'FAILED' and result.error_code == code


def test_ids_cannot_be_guessed_before_lookup(task_db, model_script):
    """模型猜产品/询价 ID 即使数值碰巧正确，也必须被证据来源门拦截。"""
    actions, _ = model_script
    actions.extend([tool('inventory.query_available', product_id=1), tool('supplier_quotes.compare', product_id=1, rfq_item_id=11)])
    result = start(task_db, '查库存并比较报价')
    assert result.status == 'FAILED' and result.error_code == 'TOOL_ERRORS'
    assert all(entry.get('status') != 'SUCCEEDED' for entry in result.trace)


def test_excluded_task_cannot_be_restored_by_planner(task_db, model_script, monkeypatch):
    """即使规划器提出报价调用，也不能执行用户已明确排除的任务。"""
    async def understand(*args, **kwargs):
        return runtime.routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"], excluded_tasks=["quotes"])
    monkeypatch.setattr(runtime.routing, "understand", understand)
    model_script[0].extend([tool("catalog.search_products", keyword="测试乙醇"),
                           tool("supplier_quotes.find_rfq_items", product_id=1)])
    result = start(task_db, "查测试乙醇库存，不用比较报价")
    assert result.error_code == "INTENT_MISMATCH"
    assert not any(entry.get("tool", "").startswith("supplier_quotes.") and entry.get("status") == "SUCCEEDED" for entry in result.trace)


def test_repeat_call_and_step_limit_stop(task_db, model_script, monkeypatch):
    """重复调用和步数预算分别终止循环，不依赖模型自觉停止。"""
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇')] * 2)
    assert start(task_db).error_code == 'REPEATED_TOOL'
    monkeypatch.setattr(runtime, 'get_settings', lambda: Settings(_env_file=None, agent_execution_mode="in_process", agent_max_steps=1))
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    assert start(task_db).error_code == 'STEP_LIMIT'


def test_context_and_time_budget_stop(task_db, model_script, monkeypatch):
    """超出上下文或模型等待预算时安全停止，不能无限积累上下文/等待。"""
    monkeypatch.setattr(runtime, 'get_settings', lambda: Settings(_env_file=None, agent_execution_mode="in_process", agent_context_max_chars=2000))
    assert start(task_db).error_code == 'CONTEXT_LIMIT'
    async def slow(*_args, **_kwargs):
        """模拟外部模型长时间未响应。"""
        await asyncio.sleep(2)
    monkeypatch.setattr(runtime.llm, 'chat', slow)
    monkeypatch.setattr(runtime, 'get_settings', lambda: Settings(_env_file=None, agent_execution_mode="in_process", agent_task_timeout_seconds=1))
    assert start(task_db).error_code == 'TASK_TIMEOUT'


def test_decision_history_budget_keeps_latest_request_and_structured_state():
    from app.modules.ai.agent_runtime import _decision_messages
    messages = [f'历史轮次 {index} ' + ('x' * 2000) for index in range(20)]
    bounded = _decision_messages(messages)
    assert len(bounded) == 6
    assert all(len(message) <= 1200 for message in bounded[:-1])
    assert bounded[-1] == messages[-1]
    # Candidate and original goal are held separately in RunState.memory_state/workflow;
    # compaction only changes this ephemeral model input, never the saved task.


def test_unknown_write_tools_cannot_create_business_data(task_db, model_script):
    """注入的写工具与 SQL 名称只形成失败记录，不触发核心业务写入。"""
    actions, _ = model_script
    actions.extend([tool('purchase_request.create_draft', product_id=1), tool('execute_sql', sql='DELETE FROM rfqs')])
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        """记录实际 SQL，检查写入仅发生于任务元数据表。"""
        statements.append(statement)
    event.listen(task_db.bind, 'before_cursor_execute', capture)
    try:
        assert start(task_db).error_code == 'TOOL_ERRORS'
    finally:
        event.remove(task_db.bind, 'before_cursor_execute', capture)
    assert all('ai_agent_tasks' in statement for statement in statements if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))


def test_history_private_and_scope_revalidated_even_for_truncated_total(task_db, model_script):
    """历史任务仅本人可见；合计涉及的仓库即使未显示明细，权限变化后也拒绝。"""
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'), tool('inventory.query_available', product_id=1, limit=1),
                    {'action': 'finish', 'evidence_steps': [2]}])
    result = start(task_db)
    with pytest.raises(ResourceNotFoundError):
        runtime.get_task(task_db, SimpleNamespace(id=9), result.id)
    task_db.execute(text('UPDATE warehouses SET manager_id=8 WHERE id=3'))
    task_db.commit()
    with pytest.raises(AuthorizationError, match='仓库'):
        runtime.get_task(task_db, USER, result.id)


def test_permission_rechecked_immediately_before_tool(task_db, model_script, monkeypatch):
    """权限在模型返回动作之后撤销时，工具仍以最新授权拒绝执行。"""
    actions, _ = model_script
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    actions.append(tool('inventory.query_available', product_id=1))
    original = runtime.llm.chat
    async def revoke(request, *args, **kwargs):
        """库存动作生成后撤销库存读取权限。"""
        reply = await original(request, *args, **kwargs)
        if not actions:
            monkeypatch.setattr(tools, 'get_user_permission_codes', lambda *_: ['master.products.read'])
        return reply
    monkeypatch.setattr(runtime.llm, 'chat', revoke)
    assert start(task_db).error_code == 'PERMISSION_DENIED'


def test_cancel_during_model_wait_cannot_be_overwritten(task_db, monkeypatch):
    """另一个请求取消任务后，模型返回也不能继续工具或把状态改回成功。"""
    async def cancel_then_reply(*_args, **_kwargs):
        """在模型响应前模拟任务取消。"""
        task_id = task_db.scalar(select(AIAgentTask.id))
        runtime.cancel_task(task_db, USER, task_id)
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(tool('catalog.search_products', keyword='测试乙醇'))))
    monkeypatch.setattr(runtime.llm, 'chat', cancel_then_reply)
    result = start(task_db)
    assert result.status == 'CANCELLED' and result.trace == []


def test_tool_exception_sanitized_and_lookup_only_cannot_claim_success(task_db, model_script, monkeypatch):
    """异常原文不进入公开轨迹；仅定位到产品不等于完成业务数据查询。"""
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'), {'action': 'finish', 'evidence_steps': [1]}])
    assert start(task_db).error_code == 'INCOMPLETE_TASK'
    def broken(*_args):
        """模拟内部工具异常，其中包含不应向用户返回的内容。"""
        raise RuntimeError('secret-server-detail')
    monkeypatch.setattr(tools, 'execute_tool', broken)
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    result = start(task_db)
    assert result.error_code == 'RUNTIME_ERROR' and 'secret-server-detail' not in result.model_dump_json()


def test_http_task_create_read_continue_cancel_and_authentication(task_db, model_script):
    """从任务 API 验证等待、追加输入、回看与取消的响应协议。"""
    app = FastAPI()
    app.include_router(router)
    allow_ai_workspace_permission(app)
    app.dependency_overrides[get_db] = lambda: task_db
    with TestClient(app) as client:
        assert client.post('/ai/agent/tasks', json={'question': '查库存'}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: USER
        actions, _ = model_script
        actions.append({'action': 'ask_user', 'question': '哪个产品？'})
        result = client.post('/ai/agent/tasks', json={'question': '查库存'}).json()
        assert result['status'] == 'WAITING_INPUT'
        assert client.get('/ai/agent/tasks/' + result['id']).json()['revision'] == result['revision']
        actions.append({'action': 'ask_user', 'question': '请明确产品规格？'})
        result = client.post('/ai/agent/tasks/' + result['id'] + '/continue', json={'question': '乙醇', 'revision': result['revision']}).json()
        assert result['messages'] == ['查库存', '乙醇']
        assert client.post('/ai/agent/tasks/' + result['id'] + '/cancel').json()['status'] == 'CANCELLED'


def test_actual_model_adapter_uses_planner_prompt_and_json_protocol(task_db, monkeypatch):
    """运行真实模型适配层，以 HTTP 替身验证请求协议；不访问外部模型服务。"""
    actions = [tool('catalog.search_products', keyword='测试乙醇'),
               tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [2]}]
    requests = []
    def respond(request):
        """模拟兼容模型的 chat/completions 响应，保留客户端发出的 JSON。"""
        payload = json.loads(request.content)
        requests.append(payload)
        messages = payload.get('messages', payload.get('input'))
        if messages[0]['content'].startswith(runtime.routing.ROUTING_PROMPT):
            assert payload['text']['format']['type'] == 'json_schema'
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'purpose': 'query', 'execution_mode': 'agent', 'tasks': ['inventory']})}]}]})
        assert payload['messages'][0]['content'] == runtime.PLANNER_PROMPT
        assert payload['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(actions.pop(0))}}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(runtime.llm.httpx, 'AsyncClient', lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs))
    assert start(task_db).status == 'SUCCEEDED'
    assert len(requests) == 4 and requests[-1]['max_tokens'] == 2048


def test_background_api_returns_id_then_persists_wait_and_continues(task_db, model_script, monkeypatch):
    """202 先返回编号；后台独立会话保存追问；刷新、版本续跑与取消沿用本人鉴权。"""
    task_db.execute(text("CREATE TABLE sys_users (id INTEGER PRIMARY KEY, status TEXT)"))
    task_db.execute(text("INSERT INTO sys_users VALUES (7, 'ACTIVE')"))
    task_db.commit()
    monkeypatch.setattr(runtime, 'SessionLocal', lambda: Session(task_db.bind))
    app = FastAPI()
    app.include_router(router)
    allow_ai_workspace_permission(app)
    app.dependency_overrides[get_db] = lambda: task_db
    actions, _ = model_script
    with TestClient(app) as client:
        assert client.post('/ai/agent/tasks/start', json={'question': '查库存'}).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: USER
        actions.append({'action': 'ask_user', 'question': '哪个产品？'})
        response = client.post('/ai/agent/tasks/start', json={'question': '查库存'})
        assert response.status_code == 202
        started = response.json()
        assert started['status'] == 'RUNNING' and started['revision'] == 0
        waiting = client.get('/ai/agent/tasks/' + started['id']).json()
        assert waiting['status'] == 'WAITING_INPUT'
        actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
            tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [3]}])
        response = client.post('/ai/agent/tasks/' + started['id'] + '/continue/start', json={
            'question': '测试乙醇', 'revision': waiting['revision']})
        assert response.status_code == 202 and response.json()['status'] == 'RUNNING'
        assert client.get('/ai/agent/tasks/' + started['id']).json()['status'] == 'SUCCEEDED'


def test_cancel_before_background_starts_does_not_call_model(task_db, model_script, monkeypatch):
    """后台启动前取消后，旧工作不得调用模型或覆盖终态。"""
    monkeypatch.setattr(runtime, 'SessionLocal', lambda: Session(task_db.bind))
    prepared = runtime.prepare_task(task_db, USER, runtime.TaskCreate(question='查测试乙醇'))
    runtime.cancel_task(task_db, USER, prepared.task_id)
    asyncio.run(runtime.run_prepared_task(prepared.task_id, USER.id, prepared.revision))
    assert runtime.get_task(task_db, USER, prepared.task_id).status == 'CANCELLED'
    assert model_script[1] == []


def test_agent_entry_rejects_non_agent_route_before_creating_task(task_db):
    from app.modules.ai import routing

    decision = routing.Understanding(
        purpose="query", execution_mode="query", tasks=["analytics"],
        sub_tasks=[routing.SubTask(id="t1", kind="analytics", question="统计采购订单数量")],
    )
    token = routing.issue_ticket(decision, USER.id, "统计采购订单数量", None)

    with pytest.raises(BusinessValidationError, match="不是库存或报价任务"):
        runtime.prepare_task(task_db, USER, runtime.TaskCreate(question="统计采购订单数量", route_token=token))
    assert task_db.scalar(select(AIAgentTask.id)) is None


def test_agent_entry_rejects_missing_tool_permission(task_db, monkeypatch):
    from app.modules.ai import routing

    monkeypatch.setattr(tools, "get_user_permission_codes",
                        lambda *_args: ["master.products.read", "warehouse.inventory.read"])
    decision = routing.Understanding(purpose="query", execution_mode="agent", tasks=["quotes"])
    token = routing.issue_ticket(decision, USER.id, "查询测试乙醇报价", None)

    with pytest.raises(AuthorizationError, match="读取权限"):
        runtime.prepare_task(task_db, USER, runtime.TaskCreate(question="查询测试乙醇报价", route_token=token))
    assert task_db.scalar(select(AIAgentTask.id)) is None


@pytest.mark.parametrize("kind,slot,number,permission,tool_name,intent", [
    ("purchase_request", "request_no", "PR20261022000031", "procurement.requests.read",
     "purchase_requests.get_by_no", "purchase_request_query"),
    ("order_trace", "po_no", "PO-26001", "procurement.orders.read",
     "purchase_orders.trace_by_no", "purchase_order_trace"),
    ("quality_acceptance", "acceptance_no", "QA20261022000031", "quality.acceptances.read",
     "quality_acceptances.get_by_no", "quality_acceptance_query"),
    ("delivery", "delivery_no", "DL20261022000031", "warehouse.deliveries.read",
     "deliveries.get_by_no", "delivery_query"),
    ("finance_reconciliation", "reconciliation_no", "FR20261022000031",
     ("finance.reconciliations.read", "finance.invoices.read", "finance.payments.read"),
     "finance_reconciliations.get_by_no", "finance_reconciliation_query"),
    ("supplier", "supplier_code", "SUP-0001", "master.suppliers.read",
     "suppliers.get_by_code", "supplier_query"),
])
def test_numbered_agent_task_starts_with_only_its_read_permission(
    task_db, monkeypatch, kind, slot, number, permission, tool_name, intent,
):
    from app.modules.ai import routing

    permissions = list(permission) if isinstance(permission, tuple) else [permission]
    monkeypatch.setattr(tools, "get_user_permission_codes", lambda *_args: permissions)
    decision = routing.Understanding(purpose="query", execution_mode="agent", tasks=[kind], slots={slot: number})
    monkeypatch.setattr(routing, "read_ticket", lambda *_args: decision)
    monkeypatch.setattr(routing, "read_ticket_pending_state_id", lambda *_args: None)
    prepared = runtime.prepare_task(task_db, USER, runtime.TaskCreate(
        question=f"查询 {number}", route_token="verified-ticket"))

    assert prepared.memory_state["goal"]["intent"] == intent
    assert prepared.memory_state["understanding"]["slots"][slot] == number


def test_agent_capability_mapping_requires_only_the_task_tool():
    from app.modules.ai import routing

    for kind, tool_name, slots in (("purchase_request", "purchase_requests.get_by_no", {}),
                                   ("order_trace", "purchase_orders.trace_by_no", {}),
                                   ("quality_acceptance", "quality_acceptances.get_by_no",
                                    {"acceptance_no": "QA20261022000031"}),
                                   ("delivery", "deliveries.get_by_no", {"delivery_no": "DL20261022000031"}),
                                   ("finance_reconciliation", "finance_reconciliations.get_by_no",
                                    {"reconciliation_no": "FR20261022000031"}),
                                   ("supplier", "suppliers.get_by_code", {"supplier_code": "SUP-0001"})):
        decision = routing.Understanding(purpose="query", execution_mode="agent", tasks=[kind], slots=slots)
        runtime._ensure_agent_capabilities(decision, {tool_name})
        with pytest.raises(AuthorizationError):
            runtime._ensure_agent_capabilities(decision, set())


def test_numbered_agent_summaries_are_deterministic_and_use_trace_answer():
    request_reply = runtime._summary([{"tool": "purchase_requests.get_by_no", "result": {
        "rows": [{"request_no": "PR20261022000031", "status": "APPROVING",
                  "purpose": "乙醇采购", "items": [{"line_no": 1}]}]}}])
    order_reply = runtime._summary([{"tool": "purchase_orders.trace_by_no", "result": {"answer": "追溯结论"}}])
    acceptance_reply = runtime._summary([{"tool": "quality_acceptances.get_by_no", "result": {
        "total_rows": 1, "rows": [{"acceptance_no": "QA20261022000031", "result": "PENDING",
                                     "certificate_complete": True, "report_available": False,
                                     "conclusion": "等待检验"}]}}])
    delivery_reply = runtime._summary([{"tool": "deliveries.get_by_no", "result": {
        "total_rows": 1, "rows": [{"delivery_no": "DL20261022000031", "status": "RECEIVED",
            "expected_arrival_date": "2026-10-22", "actual_arrival_date": None,
            "items": [{"line_no": 1, "short_quantity": 2, "document_complete": False}]}]}}])
    finance_reply = runtime._summary([{"tool": "finance_reconciliations.get_by_no", "result": {
        "total_rows": 1, "rows": [{"reconciliation_no": "FR20261022000031", "status": "CONFIRMED",
            "currency_code": "CNY", "total_amount": 100,
            "invoices": [{"status": "VERIFIED", "count": 1, "amount": 80}],
            "payments": [{"status": "PAID", "count": 1, "amount": 30}],
            "lines": [{"line_no": 1, "product_name": "乙醇", "accepted_quantity": 8,
                "reconciliation_quantity": 8, "verified_invoice_amount": 60,
                "amount_incl_tax": 100, "warnings": []}],
            "source_changed": False, "unallocated_invoices": [],
            "payment_precheck": {"verified_invoice_amount": 80, "active_payment_amount": 30,
                "max_new_payment_amount": 70, "currency_code": "CNY", "blockers": []}}]}}])
    supplier_reply = runtime._summary([{"tool": "suppliers.get_by_code", "result": {
        "total_rows": 1, "rows": [{"supplier_code": "SUP-0001", "supplier_name": "示例供应商",
            "status": "ACTIVE", "cooperation_level": "STRATEGIC", "region": "华东",
            "default_lead_days": 12}]}}])
    assert request_reply == "采购申请 PR20261022000031：APPROVING；用途：乙醇采购；明细 1 项。"
    assert order_reply == "追溯结论"
    assert acceptance_reply == "质量验收 QA20261022000031：状态 PENDING；证书齐全；报告未上传；结论：等待检验。"
    assert delivery_reply == "到货单 DL20261022000031：状态 RECEIVED；预计到货 2026-10-22；实际到货 未登记；第1行短交 2，单证未齐。"
    assert "对账单 FR20261022000031：状态 CONFIRMED；金额 100 CNY；发票 VERIFIED 1 张/80 CNY；付款 PAID 1 笔/30 CNY。" in finance_reply
    assert "第 1 行 乙醇：验收 8，对账 8；发票已核验 60/100 CNY。" in finance_reply
    assert "当前数据下单笔付款理论上限 70 CNY" in finance_reply
    assert supplier_reply == "供应商 SUP-0001（示例供应商）：状态 ACTIVE；合作级别 STRATEGIC；地区 华东；默认交期 12 天。"


@pytest.mark.parametrize("intent,tool_name,result", [
    ("purchase_request_query", "purchase_requests.get_by_no", {"total_rows": 0, "rows": []}),
    ("purchase_order_trace", "purchase_orders.trace_by_no", {"stages": [], "source_records": []}),
    ("quality_acceptance_query", "quality_acceptances.get_by_no", {"total_rows": 0, "rows": []}),
    ("delivery_query", "deliveries.get_by_no", {"total_rows": 0, "rows": []}),
    ("finance_reconciliation_query", "finance_reconciliations.get_by_no", {"total_rows": 0, "rows": []}),
    ("supplier_query", "suppliers.get_by_code", {"total_rows": 0, "rows": []}),
])
def test_numbered_agent_completion_requires_its_tool_evidence(intent, tool_name, result):
    entry = {"tool": tool_name, "result": result}
    runtime._validate_finish_evidence(intent, [entry])
    with pytest.raises(BusinessValidationError, match="INCOMPLETE_TASK"):
        runtime._validate_finish_evidence(intent, [])
    with pytest.raises(BusinessValidationError, match="INCOMPLETE_TASK"):
        runtime._validate_finish_evidence(intent, [{"tool": "catalog.search_products", "result": {"total_rows": 0}}])


@pytest.mark.parametrize("tool_name", ["purchase_requests.get_by_no", "purchase_orders.trace_by_no",
                                       "quality_acceptances.get_by_no", "deliveries.get_by_no",
                                       "finance_reconciliations.get_by_no", "suppliers.get_by_code"])
def test_revoked_numbered_tool_permission_blocks_historical_evidence(monkeypatch, tool_name):
    monkeypatch.setattr(tools, "list_tools", lambda *_args: [])
    monkeypatch.setattr(tools, "accessible_warehouse_ids", lambda *_args: None)
    monkeypatch.setattr(tools, "get_user_role_codes", lambda *_args: [])
    with pytest.raises(AuthorizationError, match="权限已变化"):
        runtime._check_trace_access(SimpleNamespace(), USER, [{
            "action": "call_tool", "tool": tool_name, "status": "SUCCEEDED", "result": {},
        }])


def test_agent_accepts_only_ticket_bound_pending_clarification(task_db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.modules.ai import routing
    from app.modules.ai.schema import PendingClarification

    pending = PendingClarification(state_id="a" * 32, question_hash="b" * 64,
        slot="product_keyword", question="查哪个产品？", options=["乙醇", "甲醇"],
        created_at=datetime.now(timezone.utc), expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        permission_hash="c" * 64, state_version=1, contract_version="1")
    decision = routing.Understanding(purpose="query", execution_mode="agent", tasks=["inventory"],
                                     slots={"product_keyword": "乙醇"})
    cleared = []
    monkeypatch.setattr(runtime.tools, "list_tools", lambda *_: [{"name": "catalog.search_products"},
        {"name": "inventory.query_available"}])
    monkeypatch.setattr(runtime.conversation_store, "load_pending_clarification", lambda *_: pending)
    monkeypatch.setattr(runtime.conversation_store, "clear_pending_clarification", lambda *args, **kwargs: cleared.append(kwargs))
    monkeypatch.setattr(routing, "read_ticket", lambda *_: decision)
    monkeypatch.setattr(routing, "read_ticket_pending_state_id", lambda *_: pending.state_id)
    prepared = runtime.prepare_task(task_db, USER, runtime.TaskCreate(
        question="乙醇", conversation_id=42, route_token="verified-ticket"))
    assert prepared.memory_state["understanding"]["execution_mode"] == "agent"
    assert cleared[0]["state_id"] == pending.state_id

    cleared.clear()
    with pytest.raises(BusinessValidationError, match="澄清答案或状态票据"):
        runtime.prepare_task(task_db, USER, runtime.TaskCreate(
            question="甲醛", conversation_id=43, route_token="verified-ticket"))
    assert not cleared


def test_disabled_user_stops_background_before_model(task_db, model_script, monkeypatch):
    """启动后用户停用，后台使用当前用户状态停止。"""
    task_db.execute(text("CREATE TABLE sys_users (id INTEGER PRIMARY KEY, status TEXT)"))
    task_db.execute(text("INSERT INTO sys_users VALUES (7, 'INACTIVE')"))
    task_db.commit()
    monkeypatch.setattr(runtime, 'SessionLocal', lambda: Session(task_db.bind))
    prepared = runtime.prepare_task(task_db, USER, runtime.TaskCreate(question='查测试乙醇'))
    asyncio.run(runtime.run_prepared_task(prepared.task_id, USER.id, prepared.revision))
    result = runtime.get_task(task_db, USER, prepared.task_id)
    assert result.status == 'FAILED' and result.error_code == 'PERMISSION_DENIED'
    assert model_script[1] == []


@pytest.fixture
def chat_task_db(task_db, monkeypatch):
    for ddl in (
        "CREATE TABLE ai_conversations (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, business_scene TEXT, permission_snapshot JSON, status TEXT, pinned BOOLEAN DEFAULT 0, last_message_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE ai_conversation_state (id INTEGER PRIMARY KEY, conversation_id INTEGER UNIQUE, thread_id TEXT UNIQUE, memory_state JSON, query_plan JSON, query_trace JSON, permission_snapshot JSON, attachment_refs JSON, state_version INTEGER DEFAULT 1, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE ai_messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, message_role TEXT, content TEXT, citations JSON, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE sys_users (id INTEGER PRIMARY KEY, status TEXT)",
        "INSERT INTO sys_users VALUES (7, 'ACTIVE')",
    ):
        task_db.execute(text(ddl))
    task_db.commit()
    monkeypatch.setattr(runtime.conversation_store, 'permission_snapshot', lambda db, user: {})
    monkeypatch.setattr(runtime, 'SessionLocal', lambda: Session(task_db.bind))
    return task_db


def test_chat_turns_persist_and_background_updates_latest_reply(chat_task_db, model_script):
    actions, contexts = model_script
    state = runtime.prepare_chat_task(chat_task_db, USER, runtime.ChatTaskCreate(question='帮我查库存'))
    result = runtime.get_task(chat_task_db, USER, state.task_id)
    assert result.conversation_id is not None
    assert len(chat_task_db.scalars(select(AIMessage)).all()) == 2
    actions.append({'action': 'ask_user', 'question': '请补充产品名称'})
    asyncio.run(runtime.run_prepared_task(state.task_id, USER.id, state.revision))
    waiting = runtime.get_task(chat_task_db, USER, state.task_id)
    first_reply = chat_task_db.scalar(select(AIMessage).where(AIMessage.message_role == 'ASSISTANT'))
    assert first_reply.content == '请补充产品名称'
    memory = chat_task_db.scalar(select(AIConversationState)).memory_state
    assert memory['goal']['status'] == 'waiting_input'
    assert memory['pending']['slot'] == 'product_identity'
    assert memory['recent_context'][-1] == {'role': 'assistant', 'text': '请补充产品名称'}
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
        tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [3]}])
    resumed = runtime.prepare_chat_continue(chat_task_db, USER, state.task_id,
        runtime.TaskContinue(question='测试乙醇', revision=waiting.revision))
    asyncio.run(runtime.run_prepared_task(resumed.task_id, USER.id, resumed.revision))
    assert [entry['role'] for entry in contexts[1]['recent_task_memory']['recent_context']] == ['user', 'assistant', 'user']
    assert contexts[1]['recent_task_memory']['recent_context'][1]['text'] == '请补充产品名称'
    assert contexts[1]['recent_task_memory']['pending'] is None
    chat_task_db.expire_all()
    replies = chat_task_db.scalars(select(AIMessage).where(AIMessage.message_role == 'ASSISTANT').order_by(AIMessage.id)).all()
    assert len(replies) == 2 and replies[0].content == '请补充产品名称'
    assert '80 千克' in replies[1].content
    assert replies[1].citations == [{'type': 'agent_task', 'task_id': state.task_id}]
    assert len(chat_task_db.scalars(select(AIConversation)).all()) == 1
    memory = chat_task_db.scalar(select(AIConversationState)).memory_state
    assert memory['turn'] == 2 and memory['goal']['status'] == 'succeeded'
    assert memory['focus']['product_name'] == '测试乙醇' and memory['focus']['resolution'] == 'resolved'
    assert [entry['role'] for entry in memory['recent_context']] == ['user', 'assistant', 'user', 'assistant']
    actions.append({'action': 'ask_user', 'question': '您想查看乙醇的哪项信息？'})
    next_turn = runtime.prepare_chat_task(chat_task_db, USER, runtime.ChatTaskCreate(
        question='它现在还有库存吗？', conversation_id=state.chat['conversation_id']))
    asyncio.run(runtime.run_prepared_task(next_turn.task_id, USER.id, next_turn.revision))
    assert contexts[4]['recent_task_memory']['focus']['product_name'] == '测试乙醇'
    assert contexts[4]['recent_task_memory']['recent_context'][-2]['text'].startswith('测试乙醇：可用库存为')
    assert contexts[4]['messages'] == ['它现在还有库存吗？']


def test_foreign_chat_cannot_create_task_or_messages(chat_task_db):
    state = runtime.prepare_chat_task(chat_task_db, USER, runtime.ChatTaskCreate(question='查库存'))
    cid = runtime.get_task(chat_task_db, USER, state.task_id).conversation_id
    with pytest.raises(BusinessValidationError):
        runtime.prepare_chat_task(chat_task_db, SimpleNamespace(id=10), runtime.ChatTaskCreate(question='查库存', conversation_id=cid))
    assert len(chat_task_db.scalars(select(AIAgentTask)).all()) == 1
    assert len(chat_task_db.scalars(select(AIMessage)).all()) == 2


@pytest.mark.parametrize('intent', ['inventory', 'quotes'])
def test_ordinary_chat_context_is_loaded_before_pronoun_task(chat_task_db, model_script, intent):
    """普通问答首次进入 Agent：历史用于名称上下文，数值仍来自本轮工具。"""
    conversation = AIConversation(user_id=USER.id, title='化学品问答', status='ACTIVE', permission_snapshot={})
    chat_task_db.add(conversation)
    chat_task_db.flush()
    chat_task_db.add_all([
        AIMessage(conversation_id=conversation.id, message_role='USER', content='测试乙醇有什么用途？'),
        AIMessage(conversation_id=conversation.id, message_role='ASSISTANT', content='测试乙醇可用作溶剂。历史示例库存999999，价格999999，均不是当前业务事实。'),
    ])
    chat_task_db.commit()
    assert chat_task_db.scalar(select(AIConversationState)) is None
    actions, contexts = model_script
    actions.append(tool('catalog.search_products', keyword='测试乙醇'))
    if intent == 'inventory':
        question = '它还有多少库存？'
        actions.extend([tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [2]}])
    else:
        question = '它的报价是多少？'
        actions.extend([tool('supplier_quotes.find_rfq_items', product_id=1),
                        tool('supplier_quotes.compare', product_id=1, rfq_item_id=11),
                        {'action': 'finish', 'evidence_steps': [3]}])
    state = runtime.prepare_chat_task(chat_task_db, USER, runtime.ChatTaskCreate(question=question, conversation_id=conversation.id))
    asyncio.run(runtime.run_prepared_task(state.task_id, USER.id, state.revision))
    result = runtime.get_task(chat_task_db, USER, state.task_id)
    assert contexts[0]['recent_task_memory']['recent_context'] == [
        {'role': 'user', 'text': '测试乙醇有什么用途？'},
        {'role': 'assistant', 'text': '测试乙醇可用作溶剂。历史示例库存999999，价格999999，均不是当前业务事实。'},
        {'role': 'user', 'text': question},
    ]
    assert result.status == 'SUCCEEDED' and not actions
    assert '999999' not in result.reply
    assert ('80 千克' if intent == 'inventory' else '8.000000 CNY/千克') in result.reply


def test_chat_api_returns_conversation_and_reloadable_task(chat_task_db, model_script):
    app = FastAPI()
    app.include_router(router, prefix='/api/v1')
    allow_ai_workspace_permission(app)
    app.dependency_overrides[get_db] = lambda: chat_task_db
    app.dependency_overrides[get_current_user] = lambda: USER
    actions, _ = model_script
    actions.append({'action': 'ask_user', 'question': '请补充产品名称'})
    with TestClient(app) as api:
        response = api.post('/api/v1/ai/agent/chat/start', json={'question': '帮我查库存'})
        assert response.status_code == 202
        task = response.json()
        history = api.get(f"/api/v1/ai/conversations/{task['conversation_id']}/messages").json()
        assert history['items'][-1]['content'] == '请补充产品名称'
        assert history['items'][-1]['citations'][0]['task_id'] == task['id']
        waiting = api.get(f"/api/v1/ai/agent/tasks/{task['id']}").json()
        assert waiting['status'] == 'WAITING_INPUT'
        actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
            tool('inventory.query_available', product_id=1), {'action': 'finish', 'evidence_steps': [3]}])
        continued = api.post(f"/api/v1/ai/agent/chat/{task['id']}/continue", json={
            'question': '测试乙醇', 'revision': waiting['revision']})
        assert continued.status_code == 202
        result = api.get(f"/api/v1/ai/agent/tasks/{task['id']}").json()
        assert result['status'] == 'SUCCEEDED'


def test_chat_history_rechecks_permissions_and_cancel_updates_reply(chat_task_db, model_script):
    from app.modules.ai.controller import messages
    state = runtime.prepare_chat_task(chat_task_db, USER, runtime.ChatTaskCreate(question='查库存'))
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
        tool('inventory.query_available', product_id=1), {'action': 'ask_user', 'question': '当前余额80.000000，是否继续？'}])
    asyncio.run(runtime.run_prepared_task(state.task_id, USER.id, state.revision))
    cid = runtime.get_task(chat_task_db, USER, state.task_id).conversation_id
    history = messages(cid, limit=100, db=chat_task_db, user=USER)
    assert '80.000000' in history.items[-1].content
    # 修改历史授权范围，不可从普通聊天历史接口读到旧库存摘要。
    chat_task_db.execute(text('UPDATE warehouses SET manager_id=8 WHERE id=1'))
    chat_task_db.commit()
    assert '80.000000' not in messages(cid, limit=100, db=chat_task_db, user=USER).items[-1].content
    chat_task_db.execute(text('UPDATE warehouses SET manager_id=7 WHERE id=1'))
    chat_task_db.commit()
    runtime.cancel_task(chat_task_db, USER, state.task_id)
    assert messages(cid, limit=100, db=chat_task_db, user=USER).items[-1].content == '任务已取消。'
    memory = chat_task_db.scalar(select(AIConversationState)).memory_state
    assert memory['goal']['status'] == 'cancelled' and memory['pending'] is None


@pytest.mark.integration
def test_task_api_against_mysql_with_authenticated_user(client, db_session, demo_password, model_script):
    """MySQL 事务回滚测试验证认证、迁移表、JSON 轨迹与 API；模型仍为替身。"""
    product = db_session.execute(select(Product.id, Product.product_code).where(Product.status == 'ACTIVE').limit(1)).first()
    assert product is not None
    headers = login(client, 'system_admin', demo_password)
    actions, _ = model_script
    actions.extend([tool('catalog.search_products', keyword=product.product_code),
        tool('inventory.query_available', product_id=product.id), {'action': 'finish', 'evidence_steps': [2]}])
    response = client.post('/api/v1/ai/agent/tasks', headers=headers, json={'question': '查询产品的账面库存'})
    assert response.status_code == 200, response.text
    result = response.json()
    if result['status'] == 'WAITING_INPUT':
        actions.clear()
        actions.extend([tool('catalog.search_products', keyword=product.product_code),
            tool('inventory.query_available', product_id=product.id), {'action': 'finish', 'evidence_steps': [3]}])
        response = client.post('/api/v1/ai/agent/tasks/' + result['id'] + '/continue', headers=headers,
            json={'question': product.product_code, 'revision': result['revision'], 'product_id': product.id})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result['status'] == 'SUCCEEDED'
    assert client.get('/api/v1/ai/agent/tasks/' + result['id'], headers=headers).json()['trace'] == result['trace']
