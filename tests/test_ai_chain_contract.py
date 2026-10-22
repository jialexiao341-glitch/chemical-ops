"""能力声明到规划和回复的契约回归；模型替身不代表语义识别准确率。"""
import json
import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import AuthorizationError, BusinessValidationError
from app.modules.ai import agent_runtime, capabilities, service, text2sql
from app.modules.ai.agent_prompt import text2sql_plan_prompt
from app.modules.ai.schema import CapabilityManifest, Intent, Understanding, QueryPlan


def run(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("替身协程不得等待真实 I/O")


def manifest(**changes):
    return CapabilityManifest(contract_version='1', digest='test', agent_tools=[],
        analytics_datasets=[], document_search=False, resource_scopes=[], **changes)


def test_product_agent_requires_its_lookup_tools():
    decision = Understanding(purpose='query', execution_mode='agent', tasks=['quotes'])
    with pytest.raises(AuthorizationError):
        agent_runtime._ensure_agent_capabilities(decision, {'supplier_quotes.compare'})
    agent_runtime._ensure_agent_capabilities(decision, set(capabilities.AGENT_TASK_REQUIREMENTS['quotes']))


def test_capability_reply_uses_current_manifest_without_a_model_call(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("能力清单介绍不需要模型猜测")
    monkeypatch.setattr(service, 'chat', forbidden)
    content, tag = run(service._compose_non_query_reply(Intent.PROJECT, 'semantic_route', '你能做什么',
        manifest=manifest(action_proposals=[{'label':'提交采购申请', 'entrypoint':'chat'}])))
    assert tag == 'capability-manifest'
    assert '提交采购申请' in content and '明确确认' in content
    assert '按产品查询' not in content


def test_guidance_receives_current_capabilities_and_does_not_execute(monkeypatch):
    async def model(request, *args, **kwargs):
        payload = json.loads(request.messages[0].content)
        assert payload['capabilities']['action_proposals'][0]['entrypoint'] == 'business_page'
        assert '未列出的能力' in kwargs['system_prompt']
        return SimpleNamespace(message=SimpleNamespace(content='从询价页面准备发送提案并核对确认。'))
    monkeypatch.setattr(service, 'chat', model)
    content, _ = run(service._compose_non_query_reply(Intent.GUIDANCE, 'semantic_route', '发送询价',
        manifest=manifest(action_proposals=[{'label':'发送询价', 'entrypoint':'business_page'}])))
    assert '提案' in content


def test_unsupported_reply_preserves_the_specific_capability_gap():
    content, _ = run(service._compose_non_query_reply(Intent.UNSUPPORTED, 'semantic_route', '付款',
        understanding={'purpose':'unsupported', 'question':'当前入口不提供付款执行，请在财务流程办理。'}))
    assert '财务流程' in content


def test_analytics_prompt_uses_the_same_available_catalog():
    prompt = text2sql_plan_prompt('', available_catalog=[{'key':'overdue_unfulfilled_orders',
        'derived_outputs':['supplier_order_count']}])
    assert 'supplier_order_count' in prompt and '单份计划' in prompt
    assert 'Schema 中其他数据集不代表本轮可用' in prompt


def test_planner_repairs_structure_without_changing_original_payload(monkeypatch):
    calls = []
    async def model(request, *args, **kwargs):
        calls.append((request.messages[0].content, kwargs['system_prompt']))
        raw = '{"dataset":"inventory","metric":"records","date_from":"2026-10-02","date_to":"2026-10-01"}'
        if len(calls) == 2:
            assert '时间范围起止顺序错误' in kwargs['system_prompt']
            raw = QueryPlan(dataset='inventory', metric='records', time_field=None).model_dump_json()
        return SimpleNamespace(message=SimpleNamespace(content=raw))
    monkeypatch.setattr(text2sql, 'chat', model)
    result = run(text2sql._generate_query_plan('{"question":"库存记录"}', SimpleNamespace(), '规划规则'))
    assert result.dataset == 'inventory' and calls[0][0] == calls[1][0]


def test_bad_plan_stops_without_a_business_query_or_old_plan_fallback(monkeypatch):
    calls = []
    async def model(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(message=SimpleNamespace(content='not json'))
    monkeypatch.setattr(text2sql, 'chat', model)
    with pytest.raises(BusinessValidationError, match='尚未执行查询'):
        run(text2sql._generate_query_plan('{}', SimpleNamespace(), '规划规则'))
    assert len(calls) == 2


def test_direct_analytics_entry_passes_current_manifest_before_routing(monkeypatch):
    from app.modules.ai import routing
    from app.modules.ai.schema import Text2SQLRequest
    expected = manifest()
    events = []
    monkeypatch.setattr(capabilities, 'build_capability_manifest', lambda *_: events.append('manifest') or expected)
    async def stop(question, context, settings, *, manifest):
        assert manifest is expected
        assert events == ['manifest', 'commit']
        raise BusinessValidationError('识别阶段停止，未执行SQL')
    monkeypatch.setattr(routing, 'understand', stop)
    with pytest.raises(BusinessValidationError, match='识别阶段停止'):
        asyncio.run(text2sql.run_text2sql(SimpleNamespace(commit=lambda: events.append('commit')),
            SimpleNamespace(id=7), Text2SQLRequest(question='统计本月订单')))
