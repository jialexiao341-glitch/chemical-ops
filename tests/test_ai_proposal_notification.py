"""提案通知随提案原子创建，且只能由提案本人解析。"""
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy import func, select
from app.modules.ai.model import AIAgentActionProposal
from app.modules.notifications.model import Notification
from tests.conftest import login
from tests.test_agent_procurement_chain import chain_catalog


def test_proposal_notification_once_owner_only_and_expiry(client, db_session, demo_password, chain_catalog, monkeypatch):
    unit, supplier, products = chain_catalog
    buyer = login(client, 'buyer', demo_password)
    manager = login(client, 'procurement_manager', demo_password)
    key = uuid4().hex
    payload = {'action_type': 'purchase_request.create_draft', 'idempotency_key': key,
               'payload': {'purpose': '通知验收', 'items': [{'product_id': products[0].id,
                  'requested_name': products[0].product_name, 'quantity': '10', 'unit_id': unit.id}]}}
    created = client.post('/api/v1/ai/action-proposals', headers=buyer, json=payload)
    assert created.status_code == 200, created.text
    confirmation_id = created.json()['confirmation_id']
    repeated = client.post('/api/v1/ai/action-proposals', headers=buyer, json=payload)
    assert repeated.status_code == 200 and repeated.json()['confirmation_id'] == confirmation_id
    proposal = db_session.scalar(select(AIAgentActionProposal).where(AIAgentActionProposal.confirmation_id == confirmation_id))
    notifications = list(db_session.scalars(select(Notification).where(Notification.related_type == 'AI_ACTION_PROPOSAL', Notification.related_id == proposal.id)).all())
    assert len(notifications) == 1 and notifications[0].recipient_id == proposal.user_id
    assert products[0].product_name not in notifications[0].content
    url = f'/api/v1/notifications/{notifications[0].id}/proposal'
    result = client.get(url, headers=buyer)
    assert result.status_code == 200 and result.json()['confirmation_id'] == confirmation_id
    assert client.get(url, headers=manager).status_code == 404
    from app.modules.ai import action_proposals
    original = action_proposals.get_user_permission_codes
    monkeypatch.setattr(action_proposals, 'get_user_permission_codes', lambda db, uid: [p for p in original(db, uid) if p != 'procurement.requests.write'])
    revoked = client.get(f'/api/v1/ai/action-proposals/{confirmation_id}', headers=buyer)
    assert revoked.status_code == 200 and revoked.json()['availability'] == 'PERMISSION_REVOKED'
    assert revoked.json()['requires_user_confirmation'] is False
    monkeypatch.setattr(action_proposals, 'get_user_permission_codes', original)
    proposal.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.flush()
    detail = client.get(f'/api/v1/ai/action-proposals/{confirmation_id}', headers=buyer)
    assert detail.status_code == 200 and detail.json()['status'] == 'EXPIRED'
    assert detail.json()['requires_user_confirmation'] is False
    listing = client.get('/api/v1/notifications', headers=buyer)
    item = next(row for row in listing.json()['items'] if row['id'] == notifications[0].id)
    assert '已过期' in item['title'] and '待确认' not in item['title']


def test_cancelled_proposal_notification_shows_current_status(client, db_session, demo_password, chain_catalog):
    unit, _, products = chain_catalog
    buyer = login(client, 'buyer', demo_password)
    body = {'action_type': 'purchase_request.create_draft', 'idempotency_key': uuid4().hex,
            'payload': {'purpose': '取消验收', 'items': [{'product_id': products[0].id,
                'requested_name': products[0].product_name, 'quantity': '4', 'unit_id': unit.id}]}}
    created = client.post('/api/v1/ai/action-proposals', headers=buyer, json=body).json()
    cancelled = client.post(f"/api/v1/ai/action-proposals/{created['confirmation_id']}/cancel", headers=buyer,
        json={'confirmation_id': created['confirmation_id'], 'preview_version': created['preview_version']})
    assert cancelled.status_code == 200
    proposal = db_session.scalar(select(AIAgentActionProposal).where(AIAgentActionProposal.confirmation_id == created['confirmation_id']))
    notice = db_session.scalar(select(Notification).where(Notification.related_type == 'AI_ACTION_PROPOSAL', Notification.related_id == proposal.id))
    listing = client.get('/api/v1/notifications', headers=buyer).json()
    item = next(row for row in listing['items'] if row['id'] == notice.id)
    assert '已取消' in item['title']
    assert client.get(f'/api/v1/notifications/{notice.id}/proposal', headers=buyer).json()['confirmation_id'] == created['confirmation_id']
    detail = client.get(f"/api/v1/ai/action-proposals/{created['confirmation_id']}", headers=buyer).json()
    assert detail['status'] == 'CANCELLED' and detail['requires_user_confirmation'] is False
