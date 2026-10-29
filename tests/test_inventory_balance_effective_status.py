from sqlalchemy import select

from app.core.auth import get_current_user
from app.main import app
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.system.model import User


def test_balance_api_reports_manual_and_quality_holds_independently(client, db_session):
    row = db_session.execute(select(InventoryBalance, InventoryBatch, QualityAcceptance)
        .join(InventoryBatch, InventoryBalance.batch_id == InventoryBatch.id)
        .join(QualityAcceptance, QualityAcceptance.delivery_id == InventoryBatch.source_delivery_id)
        .where(InventoryBalance.quantity > 0).limit(1)).first()
    assert row is not None
    balance, batch, acceptance = row
    admin = db_session.scalar(select(User).where(User.username == 'system_admin'))
    balance.status = 'AVAILABLE'
    balance.locked_quantity = 0
    batch.status = 'ACTIVE'  # 修复前的历史复检数据
    acceptance.result = 'REINSPECTION'
    db_session.flush()
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        response = client.get('/api/v1/inventory/balances', params={'batch_id': batch.id, 'page_size': 100})
        assert response.status_code == 200
        result = next(item for item in response.json()['items'] if item['id'] == balance.id)
        assert result['status'] == 'AVAILABLE'
        assert result['quality_hold'] is True
        assert result['available_quantity'] == '0'
        frozen = client.post(f'/api/v1/inventory/balances/{balance.id}/freeze', json={'reason': '测试人工冻结'})
        assert frozen.status_code == 200
        assert frozen.json()['status'] == 'FROZEN'
        assert frozen.json()['quality_hold'] is True
        unfrozen = client.post(f'/api/v1/inventory/balances/{balance.id}/unfreeze', json={'reason': '测试人工解冻'})
        assert unfrozen.status_code == 200
        assert unfrozen.json()['status'] == 'AVAILABLE'
        assert unfrozen.json()['quality_hold'] is True
        assert unfrozen.json()['available_quantity'] == '0'
        acceptance.result = 'PASSED'
        db_session.flush()
        released = client.get('/api/v1/inventory/balances', params={'batch_id': batch.id, 'page_size': 100})
        result = next(item for item in released.json()['items'] if item['id'] == balance.id)
        assert result['quality_hold'] is False
        assert result['available_quantity'] == str(balance.quantity)
        frozen = client.post(f'/api/v1/inventory/balances/{balance.id}/freeze', json={'reason': '测试独立冻结'})
        assert frozen.status_code == 200
        assert frozen.json()['quality_hold'] is False
        assert frozen.json()['available_quantity'] == '0'
        unfrozen = client.post(f'/api/v1/inventory/balances/{balance.id}/unfreeze', json={'reason': '测试批次状态'})
        assert unfrozen.status_code == 200
        batch.status = 'BLOCKED'
        db_session.flush()
        blocked = client.get('/api/v1/inventory/balances', params={'batch_id': batch.id, 'page_size': 100})
        result = next(item for item in blocked.json()['items'] if item['id'] == balance.id)
        assert result['batch_status'] == 'BLOCKED'
        assert result['status'] == 'AVAILABLE'
        assert result['available_quantity'] == '0'
    finally:
        app.dependency_overrides.pop(get_current_user, None)
