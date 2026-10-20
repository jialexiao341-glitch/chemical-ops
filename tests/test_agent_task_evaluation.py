"""评估器必须识别不完整完成和权限角色差异，不能通过误评分得到质量指标。"""
import asyncio
import json
from types import SimpleNamespace

from scripts import evaluate_agent_tasks as evaluation
from scripts.agent_evaluation_data import evaluation_db
from app.modules.ai import agent_runtime as runtime, agent_tools as tools


def _task_with_trace(trace):
    return runtime.TaskRead(id='evaluation', status='SUCCEEDED', revision=1,
        reply='answer', error_code=None, messages=[], trace=trace)


def test_object_resolution_requires_previously_returned_candidate_ids():
    catalog = {'step': 1, 'action': 'call_tool', 'status': 'SUCCEEDED',
        'tool': 'catalog.search_products', 'arguments': {'keyword': 'ethanol'},
        'result': {'rows': [{'product_id': 1}], 'sources': []}}
    inventory = {'step': 2, 'action': 'call_tool', 'status': 'SUCCEEDED',
        'tool': 'inventory.query_available', 'arguments': {'product_id': 1},
        'result': {'rows': [], 'totals': [], 'sources': []}}
    assert evaluation.check_object_resolution(_task_with_trace([catalog, inventory]))
    inventory['arguments'] = {'product_id': 99}
    assert not evaluation.check_object_resolution(_task_with_trace([catalog, inventory]))


def test_quote_comparison_requires_returned_rfqs_item_candidate():
    catalog = {'step': 1, 'action': 'call_tool', 'status': 'SUCCEEDED',
        'tool': 'catalog.search_products', 'arguments': {'keyword': 'ethanol'},
        'result': {'rows': [{'product_id': 1}]}}
    rfqs = {'step': 2, 'action': 'call_tool', 'status': 'SUCCEEDED',
        'tool': 'supplier_quotes.find_rfq_items', 'arguments': {'product_id': 1},
        'result': {'rows': [{'rfq_item_id': 11}]}}
    compare = {'step': 3, 'action': 'call_tool', 'status': 'SUCCEEDED',
        'tool': 'supplier_quotes.compare',
        'arguments': {'product_id': 1, 'rfq_item_id': 11}, 'result': {'rows': []}}
    assert evaluation.check_object_resolution(_task_with_trace([catalog, rfqs, compare]))
    compare['arguments']['rfq_item_id'] = 12
    assert not evaluation.check_object_resolution(_task_with_trace([catalog, rfqs, compare]))


def test_report_marks_answer_quality_as_unmeasured_for_synthetic_samples(tmp_path):
    report = {
        'started_at': 'test', 'model': 'test-model', 'dataset_version': 'synthetic-test',
        'planned_count': 1, 'code_revision': 'test', 'working_tree_dirty': True,
        'dataset_sha256': 'test-hash', 'cases': [{
            'id': 'T01', 'covers': ('C01',), 'status': 'SUCCEEDED', 'passed': True,
            'safety': False,
            'checks': {
                'outcome': True, 'tool_selection': True, 'object_resolution': True,
                'parameters': True, 'clarification': None, 'source_and_numbers': True,
                'answer_correctness': None, 'refusal_safety': None,
                'permission_safety': True, 'authorized_tools': True,
                'no_business_writes': True,
            },
        }],
    }
    path = tmp_path / 'evaluation.json'
    evaluation.save_report(path, report)
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['metrics']['answer_correctness'] == {'passed': 0, 'evaluated': 0}
    assert saved['evaluation_limits']['answer_correctness'] == 'HUMAN_REVIEW_REQUIRED'
    assert saved['evaluation_limits']['sample_scope'].startswith('fixed synthetic')


def test_samples_use_real_rbac_and_actor_specific_inventory():
    with evaluation_db() as db:
        assert len(tools.list_tools(db, SimpleNamespace(id=7))) == 4
        assert tools.list_tools(db, SimpleNamespace(id=20)) == []
        result = tools.execute_tool(db, SimpleNamespace(id=8), tools.ToolCall(tool='inventory.query_available', arguments={'product_id': 1}))
        task = runtime.TaskRead(id='sample', status='SUCCEEDED', revision=1, reply='', error_code=None, messages=[], trace=[
            {'step': 1, 'action': 'call_tool', 'status': 'SUCCEEDED', 'tool': result.tool, 'result': result.model_dump(mode='json')}])
        assert evaluation.check_evidence(task, actor=8)
        assert not evaluation.check_evidence(task, actor=7)


def test_finished_task_missing_requested_quote_is_failed_by_evaluator(monkeypatch):
    # 运行时现在会拒绝漏查完成；构造错误的成功快照，独立验证评分器仍能发现它。
    async def incomplete(db, user, data):
        return incomplete_inventory_task(db, user, data.question, '测试乙醇', 1)
    monkeypatch.setattr(runtime, 'create_task', incomplete)
    result = asyncio.run(evaluation.evaluate(next(c for c in evaluation.CASES if c.id == 'T03')))
    assert result['status'] == 'SUCCEEDED'
    assert not result['passed']
    assert not result['checks']['outcome'] and not result['checks']['tool_selection']
    assert result['checks']['no_business_writes']


def incomplete_inventory_task(db, user, question, keyword, product_id):
    trace = []
    for name, arguments in [('catalog.search_products', {'keyword': keyword}),
                            ('inventory.query_available', {'product_id': product_id})]:
        result = tools.execute_tool(db, user, tools.ToolCall(tool=name, arguments=arguments))
        trace.append({'step': len(trace)+1, 'action': 'call_tool', 'tool': name,
                      'arguments': arguments, 'status': 'SUCCEEDED', 'result': result.model_dump(mode='json')})
    trace.append({'step': 3, 'action': 'finish', 'status': 'SUCCEEDED', 'evidence_steps': [2]})
    return runtime.TaskRead(id='incomplete-snapshot', status='SUCCEEDED', revision=3,
        reply='当前授权仓库库存80千克、5升', error_code=None, messages=[question], trace=trace)


def test_evaluator_records_rejection_without_calling_model(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('无权入口不应调用模型')
    monkeypatch.setattr(runtime.llm, 'chat', forbidden)
    result = asyncio.run(evaluation.evaluate(next(c for c in evaluation.CASES if c.id == 'T07')))
    assert result['passed'] and result['status'] == 'REJECTED'
    assert result['model_calls'] == []
