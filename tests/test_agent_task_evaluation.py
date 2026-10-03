"""评估器必须识别不完整完成和权限角色差异，不能通过误评分得到质量指标。"""
import asyncio
import json
from types import SimpleNamespace

from scripts import evaluate_agent_tasks as evaluation
from scripts.agent_evaluation_data import evaluation_db
from app.modules.ai import agent_runtime as runtime, agent_tools as tools


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
    actions = iter([
        {'action': 'call_tool', 'tool': 'catalog.search_products', 'arguments': {'keyword': '测试乙醇'}},
        {'action': 'call_tool', 'tool': 'inventory.query_available', 'arguments': {'product_id': 1}},
        {'action': 'finish', 'evidence_steps': [2]},
    ])
    async def scripted(*_args, **_kwargs):
        return SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(actions))), usage=None)
    monkeypatch.setattr(runtime.service, 'chat', scripted)
    result = asyncio.run(evaluation.evaluate(next(c for c in evaluation.CASES if c.id == 'T03')))
    assert result['status'] == 'SUCCEEDED'
    assert not result['passed']
    assert not result['checks']['outcome'] and not result['checks']['tool_selection']
    assert result['checks']['no_business_writes']


def test_evaluator_records_rejection_without_calling_model(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError('无权入口不应调用模型')
    monkeypatch.setattr(runtime.service, 'chat', forbidden)
    result = asyncio.run(evaluation.evaluate(next(c for c in evaluation.CASES if c.id == 'T07')))
    assert result['passed'] and result['status'] == 'REJECTED'
    assert result['model_calls'] == []
