"""隔离业务库与脚本化模型验证 Agent 多步任务；不代表真实模型成功率。"""

import asyncio
import json
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
        assert response_format == {"type": "json_object"}
        if system_prompt.startswith(runtime.routing.ROUTING_PROMPT):
            # 脚本模型仅隔离执行链；真实语义效果由独立评测验证。
            payload = json.loads(request.messages[0].content)
            question = payload['question']
            switching = question.startswith('改查')
            previous = '' if switching else payload.get('context', {}).get('memory', {}).get('goal', {}).get('intent', '')
            inventory = '库存' in question or 'inventory' in previous
            quotes = '报价' in question or '询价' in question or 'quotes' in previous or 'quote' in previous
            tasks = (['inventory'] if inventory else []) + (['quotes'] if quotes else [])
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({'purpose': 'query', 'tasks': tasks or ['inventory'], 'dialogue_action': 'switch' if switching else 'continue'})))
        assert system_prompt == runtime.PLANNER_PROMPT and settings.llm_max_tokens <= 2048
        contexts.append(json.loads(request.messages[0].content))
        action = actions.pop(0)
        content = action if isinstance(action, str) else json.dumps(action, ensure_ascii=False)
        return SimpleNamespace(message=SimpleNamespace(content=content))
    monkeypatch.setattr(runtime.service, "chat", chat)
    return actions, contexts


def tool(name, **arguments):
    """构造模型动作，与服务端工具参数保持分离。"""
    return {"action": "call_tool", "tool": name, "arguments": arguments}


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
    assert '80.000000 千克' in result.reply and '8.000000 CNY/千克' in result.reply
    assert runtime.get_task(task_db, USER, result.id).trace == result.trace
    assert result.trace[-1]['evidence_steps'] == [2, 4]


def test_multiple_products_pause_and_selected_candidate_continues(task_db, model_script):
    """C18：多规格结果强制暂停；选择有效候选后重新查询并继续库存工具。"""
    task_db.execute(text("INSERT INTO md_products VALUES (3, '测试乙醇', 'ACTIVE', 'P-ETH-2', '工业级', '桶', 1)"))
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
        return runtime.routing.Understanding(purpose="query", tasks=["inventory"], excluded_tasks=["quotes"])
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
    monkeypatch.setattr(runtime.service, 'chat', slow)
    monkeypatch.setattr(runtime, 'get_settings', lambda: Settings(_env_file=None, agent_execution_mode="in_process", agent_task_timeout_seconds=1))
    assert start(task_db).error_code == 'TASK_TIMEOUT'


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
    original = runtime.service.chat
    async def revoke(request, *args, **kwargs):
        """库存动作生成后撤销库存读取权限。"""
        reply = await original(request, *args, **kwargs)
        if not actions:
            monkeypatch.setattr(tools, 'get_user_permission_codes', lambda *_: ['master.products.read'])
        return reply
    monkeypatch.setattr(runtime.service, 'chat', revoke)
    assert start(task_db).error_code == 'PERMISSION_DENIED'


def test_cancel_during_model_wait_cannot_be_overwritten(task_db, monkeypatch):
    """另一个请求取消任务后，模型返回也不能继续工具或把状态改回成功。"""
    async def cancel_then_reply(*_args, **_kwargs):
        """在模型响应前模拟任务取消。"""
        task_id = task_db.scalar(select(AIAgentTask.id))
        runtime.cancel_task(task_db, USER, task_id)
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(tool('catalog.search_products', keyword='测试乙醇'))))
    monkeypatch.setattr(runtime.service, 'chat', cancel_then_reply)
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
        if payload['messages'][0]['content'].startswith(runtime.routing.ROUTING_PROMPT):
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'purpose': 'query', 'tasks': ['inventory']})}}]})
        assert payload['messages'][0]['content'] == runtime.PLANNER_PROMPT
        assert payload['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(actions.pop(0))}}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(runtime.service.httpx, 'AsyncClient', lambda **kwargs: original_client(
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
    monkeypatch.setattr(runtime.service, '_permission_snapshot', lambda db, user: {})
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
    assert '80.000000 千克' in replies[1].content
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
    assert contexts[4]['recent_task_memory']['recent_context'][-2]['text'].startswith('测试乙醇：当前授权仓库内账面可用量')
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
    assert ('80.000000 千克' if intent == 'inventory' else '8.000000 CNY/千克') in result.reply


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
