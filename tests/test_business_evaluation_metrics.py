"""评测口径回归：错误对象、数值、来源、漏查询不能得到业务完成分。"""
import asyncio
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.modules.ai import agent_runtime as runtime, agent_tools as tools
from scripts.agent_business_cases import CASES, RFQ_CONTROLS, business_db, evidence_correct, INVENTORY, COMPARE
from scripts.evaluate_agent_business import evaluate_one, summarize, answer_facts_correct, score_row, write_atomic
from scripts import evaluate_agent_tasks as original
from scripts.queue_reliability_metrics import metrics, percentile
from tests.test_agent_task_evaluation import incomplete_inventory_task


def test_frozen_dataset_has_120_distinct_inputs_and_expected_distribution():
    assert len(CASES)==120 and len({c.id for c in CASES})==120
    assert len({(c.question,c.actor,c.seed) for c in CASES})==120
    assert Counter(c.group for c in CASES)=={'inventory':30,'quotes':30,'combined':20,'clarification':20,'safety':20}
    assert sum(not c.safety for c in CASES)==100


@pytest.mark.parametrize('case',(*CASES,*RFQ_CONTROLS),ids=lambda c:c.id)
def test_all_fixtures_and_independent_numeric_oracle(case):
    with business_db(case) as db:
        assert db.scalar(text('SELECT product_name FROM md_products WHERE id=:id'),{'id':case.expected_product})
        assert db.scalar(text('SELECT COUNT(*) FROM md_products'))==(3 if case.variant=='products' else 2)
        assert db.scalar(text('SELECT COUNT(*) FROM rfqs'))==(4 if case.variant=='rfqs' else 3)
        if case.safety: return
        for name in (INVENTORY,COMPARE):
            if name not in case.required_tools: continue
            arguments={'product_id':case.expected_product}
            if name==COMPARE: arguments['rfq_item_id']=case.expected_item
            if name==case.limit_tool: arguments['limit']=case.requested_limit
            result=tools.execute_tool(db,SimpleNamespace(id=case.actor),tools.ToolCall(tool=name,arguments=arguments))
            entry={'step':1,'action':'call_tool','status':'SUCCEEDED','tool':name,'result':result.model_dump(mode='json')}
            task=runtime.TaskRead(id='oracle',status='SUCCEEDED',revision=1,reply='',error_code=None,messages=[],trace=[entry])
            assert evidence_correct(task,case)
            wrong=replace(case,seed=case.seed+1)
            assert not evidence_correct(task,wrong)
            entry['result']['sources'][0]['record_id']=999999
            assert not evidence_correct(task,case)


def test_missing_quote_and_final_reply_fail_even_with_success_status(monkeypatch):
    case=next(c for c in CASES if c.id=='B007')
    async def incomplete(db, user, data):
        return incomplete_inventory_task(db, user, data.question, '合成乙醇', 101)
    monkeypatch.setattr(runtime, 'create_task', incomplete)
    row=evaluate_one(case,1)
    assert row['status']=='SUCCEEDED'
    assert not row['passed'] and not row['business_completed']
    assert not row['checks']['final_answer_facts']


def test_safety_does_not_credit_model_failure():
    case=next(c for c in CASES if c.id=='B012')
    row={'checks':{'outcome':True,'parameters':None},'rounds':[{'trace':[],'reply':'','error_code':'MODEL_FAILURE'}],
         'status':'FAILED'}
    scored=score_row(row,case,1)
    assert not scored['passed'] and not scored['checks']['safe_boundary']


def test_final_reply_checks_numbers_and_authorized_scope():
    case=CASES[0]
    assert answer_facts_correct('当前授权仓库账面可用量 80.000000 千克、5 升',case)
    assert not answer_facts_correct('企业全量库存 80 千克、5 升',case)
    assert not answer_facts_correct('当前授权仓库账面可用量 800 千克、5 升',case)


def test_empty_metrics_do_not_invent_success():
    assert summarize([])['business_completion']=={'passed':0,'evaluated':0,'rate':None}
    assert metrics([])['success_rate'] is None
    assert percentile([], .95) is None
    assert percentile([1,2,3,4,100], .95)==100


def test_duplicate_messages_do_not_inflate_unique_task_denominator():
    rows=[dict(group='duplicate_delivery',correct=True,duplicate_side_effects=0,missing_side_effects=0,recovery_seconds=None),
          dict(group='worker_crash',correct=False,duplicate_side_effects=1,missing_side_effects=0,recovery_seconds=20)]
    result=metrics(rows)
    assert result['unique_tasks']==2 and result['success_rate']==.5
    assert result['unrecovered']==1 and result['duplicate_side_effects']==1
    assert result['groups']['worker_crash']['recovery_p95_seconds']==20


def test_report_retries_atomic_replace_without_truncating_previous_result(tmp_path,monkeypatch):
    from pathlib import Path
    path=tmp_path/'report.json'
    path.write_text('previous',encoding='utf-8')
    replace_method=Path.replace
    attempts=[]
    def transient(source,target):
        attempts.append(1)
        assert path.read_text(encoding='utf-8')=='previous'
        if len(attempts)==1: raise OSError(22,'Injected report file error')
        return replace_method(source,target)
    monkeypatch.setattr(Path,'replace',transient)
    write_atomic(path,'new result')
    assert path.read_text(encoding='utf-8')=='new result'
    assert len(attempts)==2 and not path.with_name('report.json.tmp').exists()


def test_evaluator_exception_is_retained_as_failure():
    from contextlib import contextmanager
    @contextmanager
    def broken_fixture():
        raise RuntimeError('Injected setup failure')
        yield
    row=asyncio.run(original.evaluate(CASES[0],db_factory=broken_fixture))
    assert row['status']=='EVALUATOR_ERROR' and not row['passed']
    assert row['evaluation_error_type']=='RuntimeError'
    assert row['model_calls']==[]
