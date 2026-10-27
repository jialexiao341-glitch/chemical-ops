"""冻结前的评分器反例：不改变真实工具结果，只逐项篡改副本。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.ai import agent_runtime, agent_tools
from scripts.agent_business_cases import CASES, COMPARE, business_db, evidence_correct
from scripts.agent_evaluation_data import evaluation_db
from scripts.evaluate_agent_tasks import check_evidence


@pytest.fixture(params=[('business', 1, None), ('business', 3, None), ('business', 10, None),
                       ('business', 1, 1), ('legacy', 1, None), ('legacy', 1, 1)])
def quote_result(request):
    evaluator, seed, limit = request.param
    case = next(c for c in CASES if c.seed == seed and c.group == 'quotes'
                and not c.empty_rfq and c.requested_limit == limit)
    context = business_db(case) if evaluator == 'business' else evaluation_db()
    product_id = case.expected_product if evaluator == 'business' else 1
    item_id = case.expected_item if evaluator == 'business' else 11
    with context as db:
        arguments = {'product_id': product_id, 'rfq_item_id': item_id}
        if limit is not None:
            arguments['limit'] = limit
        output = agent_tools.execute_tool(db, SimpleNamespace(id=7),
            agent_tools.ToolCall(tool=COMPARE, arguments=arguments)).model_dump(mode='json')

    def accepted(value):
        task = agent_runtime.TaskRead(id='quote-oracle', status='SUCCEEDED', revision=1,
            reply='', error_code=None, messages=[], trace=[{
                'step': 1, 'action': 'call_tool', 'status': 'SUCCEEDED', 'tool': COMPARE, 'result': value,
            }])
        return evidence_correct(task, case) if evaluator == 'business' else check_evidence(task)

    return output, accepted


def test_normal_full_scaled_and_truncated_quotes_are_accepted(quote_result):
    output, accepted = quote_result
    assert accepted(output)
    assert output['total_rows'] == 9
    assert len(output['rows']) == (1 if output['truncated'] else 9)
    assert output['recommendation']['status'] == 'NO_RECOMMENDATION'


def _row(output, quote_id):
    return next((row for row in output['rows'] if row['quote_item_id'] == quote_id), output['rows'][0])


def _corrupt(output, mutation):
    if mutation == 'total_rows':
        output['total_rows'] = 7
    elif mutation == 'tax_exclusive':
        row = _row(output, 15)
        row['tax_included'] = not row['tax_included']
    elif mutation == 'tax_unknown':
        _row(output, 16)['tax_included'] = False
    elif mutation == 'currency':
        row = _row(output, 6)
        row['currency_code'] = 'CNY' if row['currency_code'] == 'USD' else 'USD'
    elif mutation in {'duplicate_row', 'duplicate_both'}:
        output['rows'].append(deepcopy(output['rows'][0]))
        if mutation == 'duplicate_both':
            output['sources'].append(deepcopy(output['sources'][0]))
    elif mutation == 'duplicate_source':
        output['sources'].append(deepcopy(output['sources'][0]))
    elif mutation == 'complete_cost':
        output['rows'][0]['cost_analysis']['complete'] = True
    elif mutation == 'total_cost':
        output['rows'][0]['cost_analysis']['total_cost'] = '200'
    elif mutation == 'recommendation_status':
        output['recommendation']['status'] = 'RECOMMENDED'
    elif mutation == 'recommendation_candidate':
        output['recommendation']['candidate_quote_id'] = 2
    elif mutation == 'recommendation_supplier':
        output['recommendation']['candidate_supplier_id'] = 1
    elif mutation == 'recommendation_cost':
        output['recommendation']['total_cost'] = '200'
    elif mutation == 'recommendation_currency':
        output['recommendation']['currency_code'] = 'CNY'
    elif mutation == 'unit_price':
        output['rows'][0]['unit_price'] = '999'
    elif mutation == 'foreign_source':
        output['sources'][0]['parent_id'] = 2
    elif mutation == 'rank':
        output['rows'][0]['rank'] = 1
    elif mutation == 'missing_cost':
        del output['rows'][0]['cost_analysis']
    elif mutation == 'missing_recommendation':
        del output['recommendation']
    elif mutation == 'goods_amount':
        output['rows'][0]['cost_analysis']['goods_amount'] = '999'
    elif mutation == 'missing_row':
        output['rows'].pop()
    else:
        raise AssertionError(mutation)


@pytest.mark.parametrize('mutation', [
    'total_rows', 'tax_exclusive', 'tax_unknown', 'currency',
    'duplicate_row', 'duplicate_source', 'duplicate_both', 'complete_cost', 'total_cost',
    'recommendation_status', 'recommendation_candidate', 'recommendation_supplier',
    'recommendation_cost', 'recommendation_currency', 'unit_price', 'foreign_source', 'rank',
    'missing_cost', 'missing_recommendation', 'goods_amount', 'missing_row',
])
def test_corrupted_quote_evidence_is_rejected(quote_result, mutation):
    output, accepted = quote_result
    changed = deepcopy(output)
    _corrupt(changed, mutation)
    assert accepted(changed) is False, mutation
