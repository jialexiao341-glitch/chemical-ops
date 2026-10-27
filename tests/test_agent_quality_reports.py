from datetime import datetime
from types import SimpleNamespace

from app.core.errors import ResourceNotFoundError
from app.modules.ai import agent_tools, agent_runtime
from app.modules.quality_acceptances import report_review
from app.modules.quality_acceptances.schema import QualityReportCheck, QualityReportReview


def test_visible_report_snapshots_include_review_and_conflict(monkeypatch):
    histories = [SimpleNamespace(id=11, status='CONFIRMED', reviewer_note='已核对', batch_no='B1'),
                 SimpleNamespace(id=12, status='PENDING', reviewer_note=None, batch_no='B1'),
                 SimpleNamespace(id=13, status='PENDING', reviewer_note=None, batch_no='B1')]
    monkeypatch.setattr(report_review, 'list_review_history', lambda *args: histories)
    def snapshot(db, user, acceptance_id, review_id):
        if review_id == 13:
            raise ResourceNotFoundError('无文件权限')
        return QualityReportReview(acceptance_id=acceptance_id, delivery_item_id=2, file_id=review_id,
            file_name=f'报告{review_id}.pdf', expected_batch_nos=['B1'], batch_status='MATCH',
            checks=[QualityReportCheck(item_name='纯度', report_value='99%' if review_id == 11 else '98%',
                    status='MISMATCH', source_quote='原文', source_location='第1页')], warnings=[], reviewed_at=datetime.now())
    monkeypatch.setattr(report_review, 'get_review_record', snapshot)
    result = agent_tools._quality_report_evidence(None, SimpleNamespace(id=1), 7)
    assert len(result.reviews) == 2
    assert result.reviews[0].review_status == 'CONFIRMED'
    assert result.reviews[0].checks[0].source_location == '第1页'
    assert result.conflicts[0].item_name == '纯度'
    assert '报告13' not in str(result)


def test_quality_summary_reports_visible_scope_and_is_not_acceptance_decision():
    entry = {'tool':'quality_acceptances.get_by_no', 'result': {'rows': [{
        'acceptance_no':'QA-123', 'result':'PENDING', 'certificate_complete':True,
        'report_available':True, 'conclusion':None,
        'report_reviews': {'reviews':[{'file_name':'报告.pdf','review_status':'PENDING',
          'checks':[{'item_name':'纯度','report_value':'98%', 'standard_status':'OUTSIDE_STANDARD'}]}],
          'conflicts':[], 'truncated':False}}]}}
    text = agent_runtime._summary([entry])
    assert '报告.pdf' in text and '纯度' in text and '人工' in text
    assert '### 报告 1' in text and '- **纯度**' in text


def test_historical_report_rechecks_file_permission(monkeypatch):
    import pytest
    from app.core.errors import AuthorizationError
    monkeypatch.setattr(agent_tools, 'list_tools', lambda *args: [{'name': 'quality_acceptances.get_by_no'}])
    monkeypatch.setattr(agent_tools, 'accessible_warehouse_ids', lambda *args: None)
    monkeypatch.setattr(agent_tools, 'get_user_role_codes', lambda *args: [])
    monkeypatch.setattr(agent_tools, 'get_user_permission_codes', lambda *args: ['quality.acceptances.read'])
    from app.modules.quality_acceptances import service as acceptance_service
    monkeypatch.setattr(acceptance_service, 'get_acceptance_by_no', lambda *args: SimpleNamespace(id=7))
    monkeypatch.setattr(report_review, 'get_review_record', lambda *args: (_ for _ in ()).throw(ResourceNotFoundError('无权查看文件')))
    trace = [{'status':'SUCCEEDED','action':'call_tool','tool':'quality_acceptances.get_by_no',
        'result':{'rows':[{'acceptance_no':'QA-123','report_reviews': {'reviews':[{'review_id':11}]}}]}}]
    with pytest.raises((AuthorizationError, ResourceNotFoundError)):
        agent_runtime._check_trace_access(None, SimpleNamespace(id=1), trace)


def test_actual_report_lookup_and_revoked_file_is_filtered(db_session, monkeypatch):
    from sqlalchemy import select
    from app.modules.system.model import User
    from app.modules.quality_acceptances.model import QualityReportReviewRecord, QualityAcceptance
    from app.modules.files import service as file_service
    from app.modules.ai.schema import QualityAcceptanceInput
    db = db_session
    user = db.scalar(select(User).where(User.username == 'system_admin'))
    record = db.scalar(select(QualityReportReviewRecord).order_by(QualityReportReviewRecord.id.desc()))
    assert record is not None
    acceptance = db.get(QualityAcceptance, record.acceptance_id)
    result = agent_tools.get_quality_acceptance(db, user, QualityAcceptanceInput(acceptance_no=acceptance.acceptance_no))
    assert any(review.review_id == record.id for review in result.rows[0].report_reviews.reviews)
    from app.modules.deliveries.model import Delivery
    from app.modules.ai.schema import DeliveryInput
    delivery = db.get(Delivery, acceptance.delivery_id)
    delivery_result = agent_tools.get_delivery(db, user, DeliveryInput(delivery_no=delivery.delivery_no))
    assert any(group.acceptance_no == acceptance.acceptance_no and
        any(review.review_id == record.id for review in group.report_reviews.reviews)
        for group in delivery_result.rows[0].quality_reports)
    original = file_service.get_file
    def without_file(session, actor, file_id):
        if file_id == record.file_id:
            raise ResourceNotFoundError('无权访问')
        return original(session, actor, file_id)
    monkeypatch.setattr(file_service, 'get_file', without_file)
    filtered = agent_tools.get_quality_acceptance(db, user, QualityAcceptanceInput(acceptance_no=acceptance.acceptance_no))
    assert all(review.review_id != record.id for review in filtered.rows[0].report_reviews.reviews)


def test_delivery_tool_does_not_read_quality_without_permission(monkeypatch):
    from app.modules.deliveries import service as delivery_service
    from app.modules.ai.schema import DeliveryInput
    delivery = SimpleNamespace(id=7, delivery_no='DL-123', status='IN_TRANSIT',
        expected_arrival_date=None, actual_arrival_date=None, items=[])
    monkeypatch.setattr(delivery_service, 'get_delivery_by_no', lambda *args: delivery)
    monkeypatch.setattr(agent_tools, 'get_user_role_codes', lambda *args: [])
    monkeypatch.setattr(agent_tools, 'get_user_permission_codes', lambda *args: ['warehouse.deliveries.read'])
    result = agent_tools.get_delivery(None, SimpleNamespace(id=1), DeliveryInput(delivery_no='DL-123'))
    assert result.rows[0].quality_reports is None
    assert [source.resource for source in result.sources] == ['deliveries']


def test_report_limit_discloses_truncation(monkeypatch):
    histories = [SimpleNamespace(id=i, status='PENDING', reviewer_note=None, batch_no='B') for i in range(1, 11)]
    monkeypatch.setattr(report_review, 'list_review_history', lambda *args: histories)
    monkeypatch.setattr(report_review, 'get_review_record', lambda db, user, acceptance_id, review_id:
        QualityReportReview(acceptance_id=acceptance_id, delivery_item_id=2, file_id=review_id,
            file_name=f'{review_id}.pdf', expected_batch_nos=[], batch_status='UNVERIFIED',
            checks=[], warnings=[], reviewed_at=datetime.now()))
    evidence = agent_tools._quality_report_evidence(None, SimpleNamespace(id=1), 7)
    assert len(evidence.reviews) == 8 and evidence.truncated


def test_historical_successful_task_is_reformatted_from_original_evidence():
    result = {'tool': 'quality_acceptances.get_by_no', 'rows': [{'acceptance_no': 'QA-123',
        'result': 'PENDING', 'certificate_complete': True, 'report_available': True, 'conclusion': None,
        'report_reviews': {'reviews': [{'file_name': '报告.pdf', 'review_status': 'PENDING',
            'checks': [{'item_name': '纯度', 'report_value': '98%', 'standard_status': 'OUTSIDE_STANDARD'}]}],
            'conflicts': [], 'truncated': False}}]}
    trace = [{'step': 1, 'action': 'call_tool', 'status': 'SUCCEEDED', 'tool': result['tool'], 'result': result},
             {'step': 2, 'action': 'finish', 'status': 'SUCCEEDED', 'evidence_steps': [1]}]
    task = SimpleNamespace(status='SUCCEEDED', reply='旧格式', payload={'trace': trace})
    reply = agent_runtime._formatted_task_reply(task)
    assert '### 报告 1' in reply and '**纯度**' in reply and '**PENDING**' in reply
    assert task.reply == '旧格式'
    assert agent_runtime._formatted_task_reply(SimpleNamespace(status='FAILED', reply='原错误', payload={'trace': []})) == '原错误'


def test_history_keeps_earlier_turn_when_same_task_has_continued(monkeypatch):
    from app.modules.ai.history_access import visible_message
    task = SimpleNamespace(status='SUCCEEDED', reply='新排版')
    monkeypatch.setattr(agent_runtime, 'get_task', lambda *args: task)
    monkeypatch.setattr(agent_runtime, '_load', lambda *args: SimpleNamespace(reply='原始最终答案'))
    old = SimpleNamespace(message_role='ASSISTANT', content='此前追问', citations=[{'type':'agent_task', 'task_id':'1'}])
    current = SimpleNamespace(message_role='ASSISTANT', content='原始最终答案', citations=old.citations)
    assert visible_message(None, None, old)[0] == '此前追问'
    assert visible_message(None, None, current)[0] == '新排版'
