"""评估器必须识别不完整完成和权限角色差异，不能通过误评分得到质量指标。"""
import asyncio
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
