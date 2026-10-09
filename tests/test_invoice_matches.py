"""模拟发票验证人工行匹配、额度释放、来源变化和双人复核。"""

from decimal import Decimal
from uuid import uuid4

import pytest

from .conftest import login
from .test_reconciliation_items import scenario, create_reconciliation, complete_return  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture
def matched_scenario(client, scenario, demo_password):
    s = scenario
    rec_id = create_reconciliation(client, s)
    path = f"/api/v1/finance/reconciliations/{rec_id}"
    assert client.post(path + "/confirm", headers=s["headers"], json={}).status_code == 200
    basis = client.get(path + "/items", headers=s["headers"]).json()
    return {**s, "rec_id": rec_id, "basis": basis, "clerk": login(client, "finance_clerk", demo_password), "manager": login(client, "finance_manager", demo_password)}


def invoice(client, s, excl, tax):
    response = client.post('/api/v1/finance/invoices', headers=s['clerk'], json={
        'reconciliation_id': s['rec_id'], 'invoice_number': f'DEV-SIM-{uuid4().hex[:12]}',
        'invoice_date': '2026-09-30', 'amount_excl_tax': excl, 'tax_amount': tax,
        'amount_incl_tax': str(Decimal(excl) + Decimal(tax)), 'note': '开发模拟发票，非真实开票',
    })
    assert response.status_code == 201, response.text
    return f"/api/v1/finance/invoices/{response.json()['id']}"


def allocation(s, row, excl, tax, note=None):
    return dict(reconciliation_item_id=s['basis']['items'][row]['id'], amount_excl_tax=excl, tax_amount=tax, difference_note=note)


def save(client, s, path, rows):
    return client.post(path + '/matches', headers=s['clerk'], json={'reconciliation_version': s['basis']['version_no'], 'allocations': rows})


def test_multiple_invoices_multi_line_and_history(client, matched_scenario):
    s = matched_scenario
    first = invoice(client, s, '50', '6.5')
    assert save(client, s, first, [allocation(s, 0, '50', '6.5', '按票面分配，比例舍入差异由复核人确认')]).status_code == 200
    assert client.post(first + '/submit', headers=s['clerk']).status_code == 200
    assert client.post(first + '/verify', headers=s['manager']).status_code == 200
    second = invoice(client, s, '251.23', '6.66')
    # 不完整匹配可以留存草稿，但不能提交。
    draft = save(client, s, second, [allocation(s, 1, '200', '0')])
    assert draft.status_code == 200 and draft.json()['warnings']
    assert client.post(second + '/submit', headers=s['clerk']).status_code == 400
    saved = save(client, s, second, [allocation(s, 0, '51.23', '6.66', '分次开票尾差按票面处理'), allocation(s, 1, '200', '0')])
    assert saved.status_code == 200, saved.text
    assert len(saved.json()['versions']) == 2
    assert saved.json()['versions'][1]['allocations'][0]['amount_excl_tax'] == '200'
    assert client.post(second + '/submit', headers=s['clerk']).status_code == 200
    assert client.post(second + '/verify', headers=s['manager']).status_code == 200
    analysis = client.get(f"/api/v1/insights/finance-difference/{s['order'].id}", headers=s['clerk'])
    assert any('已核验开票' in row['label'] for row in analysis.json()['evidence'])
    assert client.post(second + '/matches', headers=s['clerk'], json={'reconciliation_version': 1, 'allocations': [allocation(s, 1, '200', '0')]}).status_code == 400


def test_duplicate_foreign_line_tax_difference_and_precision(client, matched_scenario):
    s = matched_scenario
    path = invoice(client, s, '99', '14')
    row = allocation(s, 0, '99', '14')
    assert save(client, s, path, [row, row]).status_code == 400
    assert save(client, s, path, [{**row, 'reconciliation_item_id': 999999999}]).status_code == 400
    assert save(client, s, path, [{**row, 'tax_amount': '0.1234567'}]).status_code == 422
    assert save(client, s, path, [row]).status_code == 200
    blocked = client.post(path + '/submit', headers=s['clerk'])
    assert blocked.status_code == 400 and '差异处理说明' in blocked.text
    assert save(client, s, path, [{**row, 'difference_note': '按模拟票面金额处理税差，待独立复核'}]).status_code == 200
    assert client.post(path + '/submit', headers=s['clerk']).status_code == 200
    assert client.post(path + '/verify', headers=s['headers']).status_code == 200


def test_rejection_releases_quota_and_resubmit_rechecks(client, matched_scenario):
    s = matched_scenario
    first = invoice(client, s, '200', '0')
    assert save(client, s, first, [allocation(s, 1, '200', '0')]).status_code == 200
    assert client.post(first + '/submit', headers=s['clerk']).status_code == 200
    assert client.post(first + '/reject', headers=s['manager'], json={'reason': '模拟票面需更正'}).status_code == 200
    replacement = invoice(client, s, '200', '0')
    assert save(client, s, replacement, [allocation(s, 1, '200', '0')]).status_code == 200
    assert client.post(first + '/submit', headers=s['clerk']).status_code == 400
    assert client.post(replacement + '/void', headers=s['clerk'], json={'reason': '模拟作废'}).status_code == 200
    assert client.post(first + '/submit', headers=s['clerk']).status_code == 200
    assert len(client.get(replacement + '/matches', headers=s['clerk']).json()['versions']) == 1


def test_source_changes_and_self_review_blocked(client, matched_scenario):
    s = matched_scenario
    path = invoice(client, s, '200', '0')
    # 管理员具有核验权限，但不能复核自己保存的匹配。
    response = client.post(path + '/matches', headers=s['headers'], json={'reconciliation_version': 1, 'allocations': [allocation(s, 1, '200', '0')]})
    assert response.status_code == 200
    assert client.post(path + '/submit', headers=s['clerk']).status_code == 200
    blocked = client.post(path + '/verify', headers=s['headers'])
    assert blocked.status_code == 400 and '复核人' in blocked.text
    complete_return(client, s)
    changed = client.get(path + '/matches', headers=s['clerk'])
    assert changed.json()['source_changed']
    blocked = client.post(path + '/verify', headers=s['manager'])
    assert blocked.status_code == 400 and '来源已变化' in blocked.text


def test_readonly_user_cannot_match_or_void(client, matched_scenario, demo_password):
    s = matched_scenario
    path = invoice(client, s, '200', '0')
    viewer = login(client, 'finance_viewer', demo_password)
    assert client.get(path + '/matches', headers=viewer).status_code in {403, 404}
    assert client.post(path + '/matches', headers=viewer, json={'reconciliation_version': 1, 'allocations': [allocation(s, 1, '200', '0')]}).status_code in {403, 404}
    assert client.post(path + '/void', headers=viewer, json={'reason': '越权'}).status_code in {403, 404}


def test_line_overallocation_and_wrong_version_blocked(client, matched_scenario):
    s = matched_scenario
    path = invoice(client, s, '120', '13')
    assert save(client, s, path, [allocation(s, 0, '120', '13', '模拟超额')]).status_code == 200
    response = client.post(path + '/submit', headers=s['clerk'])
    assert response.status_code == 400 and '超过应付额度' in response.text
    response = client.post(path + '/matches', headers=s['clerk'], json={'reconciliation_version': 2, 'allocations': [allocation(s, 1, '200', '0')]})
    assert response.status_code == 400


def test_invoice_change_reopens_difference_review(client, matched_scenario):
    s = matched_scenario
    path = invoice(client, s, '200', '0')
    assert save(client, s, path, [allocation(s, 1, '200', '0')]).status_code == 200
    base = f"/api/v1/insights/finance-difference/{s['order'].id}"
    snapshot = client.post(base + '/snapshots', headers=s['clerk']).json()
    checks = client.post(base + '/checks', headers=s['clerk'], params={'snapshot_id': snapshot['id']}).json()
    check = next(row for row in checks if row['scope_key'].startswith('INVOICE:'))
    url = base + f"/checks/{check['id']}"
    assert client.patch(url, headers=s['clerk'], json={'status': 'CHECKED', 'finding': '  '}).status_code == 400
    assert client.patch(url, headers=s['clerk'], json={'status': 'CHECKED', 'finding': '已核对模拟票面与行匹配'}).status_code == 200
    assert client.patch(url, headers=s['manager'], json={'status': 'VERIFIED'}).status_code == 200
    assert client.patch(url, headers=s['manager'], json={'finding': '静默改写已复核结论'}).status_code == 400
    assert save(client, s, path, [allocation(s, 1, '200', '0')]).status_code == 200
    current = client.get(base + '/checks', headers=s['clerk']).json()
    assert next(row for row in current if row['id'] == check['id'])['status'] == 'OPEN'
    events = client.get(url + '/events', headers=s['clerk']).json()
    assert events[-1]['status'] == 'OPEN' and '状态变化' in events[-1]['finding']
