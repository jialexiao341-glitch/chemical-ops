"""询价条件与产品身份分离，候选选择的真实 SQL 与状态恢复回归。"""
import asyncio

import httpx
import pytest
from sqlalchemy import select, text

from app.core.errors import AuthorizationError, BusinessValidationError
from app.modules.ai import agent_runtime as runtime
from app.modules.ai.model import AIAgentTask
from tests.test_agent_runtime import USER, model_script, task_db, start, tool
from tests.test_agent_read_tools import tool_db


def waiting_rfq(db, actions, question='比较测试乙醇报价'):
    db.execute(text("INSERT INTO rfqs VALUES (4, 'RFQ-OWN-B', 7, 'SENT')"))
    db.execute(text("INSERT INTO rfq_items VALUES (41, 4, 1, '工业级', NULL)"))
    db.commit()
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
                    tool('supplier_quotes.find_rfq_items', product_id=1)])
    result = start(db, question)
    assert result.status == 'WAITING_INPUT'
    return result


@pytest.mark.parametrize('number', ['Q-9', '2026/09-A', 'legacy_17', 'abc.002'])
def test_nonstandard_number_never_replaces_verified_product(task_db, model_script, number):
    task_db.execute(text('UPDATE rfqs SET rfq_no=:number WHERE id=1'), {'number': number})
    task_db.commit()
    actions, contexts = model_script
    actions.extend([tool('catalog.search_products', keyword='测试乙醇'),
                    tool('inventory.query_available', product_id=1),
                    tool('catalog.search_products', keyword=number),
                    tool('supplier_quotes.compare', product_id=1, rfq_item_id=11),
                    {'action': 'finish', 'evidence_steps': [2, 4]}])
    result = start(task_db, f'先核对测试乙醇库存，再比较{number}报价。')
    assert result.status == 'SUCCEEDED'
    assert result.trace[2]['tool'] == 'supplier_quotes.find_rfq_items'
    assert result.trace[2]['arguments'] == {'product_id': 1, 'rfq_no': number}
    assert contexts[0]['workflow']['rfq_no'] == number


@pytest.mark.parametrize('question,expected', [
    ('查询产品P-ETH库存', None), ('比较测试乙醇报价', None),
    ('比较P-ETH报价', None),
    ('比较测试乙醇在Q-9的有效最新报价', 'Q-9'),
    ('询价编号华东采购-九月的报价', '华东采购-九月'),
    ('查库存和2026/09-A报价', '2026/09-A'),
])
def test_rfq_condition_uses_semantic_position(question, expected):
    assert runtime._rfq_condition(question) == expected


def test_product_code_quote_request_is_not_forced_into_rfq_filter(task_db, model_script):
    model_script[0].extend([tool('catalog.search_products', keyword='P-ETH'),
        tool('supplier_quotes.find_rfq_items', product_id=1),
        tool('supplier_quotes.compare', product_id=1, rfq_item_id=11),
        {'action': 'finish', 'evidence_steps': [3]}])
    result = start(task_db, '比较P-ETH报价')
    assert result.status == 'SUCCEEDED'
    assert 'rfq_no' not in result.trace[1]['arguments']


def test_pending_rfq_is_structured_and_resume_reads_current_quotes(task_db, model_script, monkeypatch):
    result = waiting_rfq(task_db, model_script[0])
    payload = task_db.scalar(select(AIAgentTask.payload).where(AIAgentTask.id == result.id))
    pending = payload['workflow']['pending']
    assert pending['entity'] == 'rfq_item' and pending['revision'] == result.revision
    assert {row['rfq_item_id'] for row in pending['candidates']} == {11, 41}
    assert payload['memory_state']['pending']['slot'] == 'rfq_identity'
    task_db.execute(text('UPDATE supplier_quote_items SET unit_price=17 WHERE id=2'))
    task_db.commit()
    async def unexpected_model(*args, **kwargs):
        pytest.fail('结构化选择续答不应重新调用模型识别编号')
    monkeypatch.setattr(runtime.service, 'chat', unexpected_model)
    continued = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='选择 RFQ-OWN', revision=result.revision, rfq_item_id=11)))
    assert continued.status == 'SUCCEEDED' and '17.000000 CNY/千克' in continued.reply
    assert [e.get('tool') for e in continued.trace[2:-1]] == [
        'catalog.search_products', 'supplier_quotes.find_rfq_items', 'supplier_quotes.compare']
    assert continued.trace[-1]['evidence_steps'] == [5]


def test_text_selection_matches_full_number_and_rehydrates_workflow(task_db, model_script):
    result = waiting_rfq(task_db, model_script[0])
    prepared = runtime.prepare_continue(task_db, USER, result.id,
        runtime.TaskContinue(question='选择 RFQ-OWN，继续比较', revision=result.revision))
    payload = task_db.scalar(select(AIAgentTask.payload).where(AIAgentTask.id == result.id))
    # 模拟队列从 JSON 快照恢复；新轮没有沿用 verified 或旧业务证据。
    restored = runtime.RunState(result.id, prepared.revision, payload['messages'], payload['trace'],
        payload['turn_start'], payload['selected_product'], payload['selected_rfq_item'],
        memory_state=payload['memory_state'], workflow=runtime.Workflow.model_validate(payload['workflow']))
    assert restored.verified_product is None and restored.workflow.rfq_no == 'RFQ-OWN'
    continued = asyncio.run(runtime._drive(task_db, USER, restored, runtime.get_settings()))
    assert continued.status == 'SUCCEEDED' and continued.trace[-1]['evidence_steps'] == [5]


def test_wrong_entity_selection_cannot_reuse_old_product_candidate(task_db, model_script):
    result = waiting_rfq(task_db, model_script[0])
    with pytest.raises(BusinessValidationError, match='本轮'):
        runtime.prepare_continue(task_db, USER, result.id,
            runtime.TaskContinue(question='选择', revision=result.revision, product_id=1))


@pytest.mark.parametrize('change', ["UPDATE rfqs SET status='CLOSED' WHERE id=1",
                                   "UPDATE md_products SET status='INACTIVE' WHERE id=1",
                                   'UPDATE rfq_items SET product_id=2 WHERE id=11'])
def test_stale_selection_waits_again_without_quote_execution(task_db, model_script, change):
    result = waiting_rfq(task_db, model_script[0])
    task_db.execute(text(change))
    task_db.commit()
    continued = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='选择', revision=result.revision, rfq_item_id=11)))
    assert continued.status == 'WAITING_INPUT'
    assert '已不在当前可用候选' in continued.reply
    assert not any(e.get('tool') == 'supplier_quotes.compare' for e in continued.trace)


def test_changed_rfq_owner_blocks_continuation(task_db, model_script):
    result = waiting_rfq(task_db, model_script[0])
    task_db.execute(text('UPDATE rfqs SET requester_id=8 WHERE id=1'))
    task_db.commit()
    with pytest.raises(AuthorizationError):
        runtime.prepare_continue(task_db, USER, result.id,
            runtime.TaskContinue(question='选择', revision=result.revision, rfq_item_id=11))


def test_combined_resume_refreshes_inventory_and_preserves_limit(task_db, model_script):
    actions = model_script[0]
    result = waiting_rfq(task_db, actions, '查测试乙醇库存和报价；库存明细只返回1条。')
    task_db.execute(text('UPDATE inventory_balances SET quantity=150 WHERE id=1'))
    task_db.commit()
    continued = asyncio.run(runtime.continue_task(task_db, USER, result.id,
        runtime.TaskContinue(question='选择', revision=result.revision, rfq_item_id=11)))
    assert continued.status == 'SUCCEEDED' and '130.000000 千克' in continued.reply
    inventory = next(e for e in continued.trace if e.get('tool') == 'inventory.query_available')
    assert inventory['arguments']['limit'] == 1 and inventory['result']['truncated']
    assert len(continued.trace[-1]['evidence_steps']) == 2


def test_explicit_product_switch_clears_previous_ids_and_rfq(task_db, model_script):
    result = waiting_rfq(task_db, model_script[0])
    task_db.execute(text("INSERT INTO md_products VALUES (3, '新产品', 'ACTIVE', 'NEW-P', '工业级', '桶', 1)"))
    task_db.commit()
    prepared = runtime.prepare_continue(task_db, USER, result.id,
        runtime.TaskContinue(question='改查新产品库存', revision=result.revision))
    model_script[0].extend([tool('catalog.search_products', keyword='新产品'),
                          tool('inventory.query_available', product_id=3),
                          {'action': 'finish', 'evidence_steps': [4]}])
    continued = asyncio.run(runtime._drive(task_db, USER, prepared, runtime.get_settings()))
    assert continued.status == 'SUCCEEDED' and '新产品' in continued.reply
    assert task_db.scalar(select(AIAgentTask.payload).where(AIAgentTask.id == result.id))['memory_state']['goal']['intent'] == 'inventory_query'


def test_format_retry_is_bounded_and_does_not_repeat_tool(task_db, model_script):
    actions, contexts = model_script
    actions.extend(['not json', tool('catalog.search_products', keyword='测试乙醇'),
                    tool('inventory.query_available', product_id=1),
                    {'action': 'finish', 'evidence_steps': [2]}])
    result = start(task_db)
    assert result.status == 'SUCCEEDED'
    assert 'format_correction' in contexts[1]
    assert len([e for e in result.trace if e.get('tool') == 'catalog.search_products']) == 1


def test_transport_failure_has_separate_error_code(task_db, monkeypatch):
    async def disconnected(*args, **kwargs):
        raise httpx.ConnectError('test transport')
    async def understand(*args, **kwargs):
        return runtime.routing.Understanding(purpose='query', tasks=['inventory'])
    monkeypatch.setattr(runtime.routing, 'understand', understand)
    monkeypatch.setattr(runtime.service, 'chat', disconnected)
    assert start(task_db).error_code == 'MODEL_SERVICE_ERROR'


def test_combined_finish_cannot_omit_quote_evidence(task_db, model_script):
    model_script[0].extend([tool('catalog.search_products', keyword='测试乙醇'),
                          tool('inventory.query_available', product_id=1),
                          {'action': 'finish', 'evidence_steps': [2]}])
    result = start(task_db, '查测试乙醇库存并比较报价')
    assert result.status == 'FAILED' and result.error_code == 'INCOMPLETE_TASK'
