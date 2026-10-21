"""统一候选版本校验与批次续跑。"""
import asyncio
import time
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.core.config import get_settings
from app.modules.ai import multi_intent
from app.modules.ai.schema import PendingChoice, SubTask, TaskResult, TaskStatus, Understanding


def test_choice_rejects_stale_or_foreign_candidate():
    from app.modules.ai.candidate_resolution import validate_selection
    pending = PendingChoice(entity='product', lookup_arguments={'keyword': '试剂'},
                            candidates=[{'product_id': 7}], revision=2)
    assert validate_selection(pending, entity='product', selected_id=7, revision=2) == 7
    for entity, selected_id, revision in [('rfq_item', 7, 2), ('product', 8, 2), ('product', 7, 1)]:
        with pytest.raises(BusinessValidationError):
            validate_selection(pending, entity=entity, selected_id=selected_id, revision=revision)


def test_batch_choice_survives_reload_and_preserves_successes(monkeypatch):
    from app.modules.ai.schema import BatchChoice
    pending = PendingChoice(entity='product', lookup_arguments={'keyword': '试剂'},
                            candidates=[{'product_id': 7}, {'product_id': 8}], revision=2)
    completed = TaskResult(id='t1', kind='inventory', question='已完成库存查询', status=TaskStatus.SUCCEEDED,
                           answer='已完成', execution_plan={'slots': {'product_keyword': '已完成'}})
    waiting = TaskResult(id='t2', kind='inventory', question='试剂库存', status=TaskStatus.WAITING_INPUT,
                        execution_plan={'slots': {'product_keyword': '试剂'}}, pending=pending)
    previous = [completed.model_dump(mode='json'), waiting.model_dump(mode='json')]
    decision = Understanding(purpose='query', execution_mode='batch', dialogue_action='continue', tasks=['inventory'], sub_tasks=[
        SubTask(id=item.id, kind=item.kind, question=item.question, slots=item.execution_plan['slots'])
        for item in (completed, waiting)])
    monkeypatch.setattr(multi_intent, 'history_accessible', lambda *_: True)
    called = []
    def execute(db, user, task, result, products, **kwargs):
        called.append((task.id, kwargs.get('selection')))
        result.status = TaskStatus.SUCCEEDED
        result.answer = '新结果'
    monkeypatch.setattr(multi_intent, 'execute_product_task', execute)
    db = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
    choice = BatchChoice(task_id='t2', entity='product', selected_id=8, revision=2)
    report = asyncio.run(multi_intent.execute_batch(db, object(), decision, get_settings(),
                           previous_tasks=previous, selection=choice))
    assert report.tasks[0].answer == '已完成'
    assert report.tasks[1].status == TaskStatus.SUCCEEDED
    assert called == [('t2', choice)]


def test_sync_product_tool_stage_does_not_block_event_loop(monkeypatch):
    decision = Understanding.model_construct(purpose='query', execution_mode='batch', tasks=['inventory'], sub_tasks=[
        SubTask(id='t1', kind='inventory', question='查询乙醇库存', slots={'product_keyword': '乙醇'})])
    monkeypatch.setattr(multi_intent, 'history_accessible', lambda *_: True)
    def slow_sync_stage(*_args, **_kwargs):
        time.sleep(0.15)
    monkeypatch.setattr(multi_intent, 'execute_product_task', slow_sync_stage)
    db = SimpleNamespace(commit=lambda: None, rollback=lambda: None)

    async def check_progress():
        progressed = False
        async def heartbeat():
            nonlocal progressed
            await asyncio.sleep(0.02)
            progressed = True
        await asyncio.gather(
            multi_intent.execute_batch(db, object(), decision, get_settings()), heartbeat())
        return progressed

    assert asyncio.run(check_progress())
