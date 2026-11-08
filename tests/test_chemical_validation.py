import pytest
from pydantic import ValidationError

from app.modules.chemicals.schema import ChemicalCreate, ChemicalUpdate, ChemicalRead


@pytest.mark.parametrize('payload', [
    {'chemical_name': '水'},
    {'chemical_name': '  ', 'cas_no': '7732-18-5'},
    {'chemical_name': '水', 'cas_no': '7732-18-4'},
    {'chemical_name': '水', 'cas_no': '7732185'},
    {'chemical_name': '水', 'cas_no': '7732-18-5', 'english_name': '123'},
    {'chemical_name': '水', 'cas_no': '7732-18-5', 'molecular_weight': 0},
    {'chemical_name': '水', 'cas_no': '7732-18-5', 'chemical_formula': 'H2O!'},
    {'chemical_name': '水', 'cas_no': '7732-18-5', 'source_text': 'https://'},
])
def test_invalid_create_fields(payload):
    with pytest.raises(ValidationError):
        ChemicalCreate.model_validate(payload)


def test_valid_create_and_optional_fields():
    chemical = ChemicalCreate.model_validate({'chemical_name': ' 水 ', 'cas_no': ' 7732-18-5 ', 'english_name': 'Water', 'chemical_formula': 'H2O', 'molecular_weight': '18.015', 'source_text': '供应商 SDS'})
    assert chemical.chemical_name == '水'
    assert chemical.cas_no == '7732-18-5'


@pytest.mark.parametrize('value', ['', None, '7732-18-4'])
def test_update_rejects_invalid_explicit_cas(value):
    with pytest.raises(ValidationError):
        ChemicalUpdate.model_validate({'cas_no': value})


def test_legacy_null_cas_can_be_read():
    from datetime import datetime
    record = {'id': 1, 'chemical_name': '旧数据', 'cas_no': None, 'status': 'ACTIVE', 'created_at': datetime.now(), 'updated_at': datetime.now()}
    assert ChemicalRead.model_validate(record).cas_no is None


@pytest.mark.parametrize('formula', ['Ca(OH)2', 'CuSO4·5H2O', '(NH4)2SO4'])
def test_common_formula_notation(formula):
    assert ChemicalCreate(chemical_name='样本', cas_no='7732-18-5', chemical_formula=formula).chemical_formula == formula


def test_legacy_record_requires_cas_before_update(monkeypatch):
    from types import SimpleNamespace
    from app.core.errors import BusinessValidationError
    from app.modules.chemicals import service
    monkeypatch.setattr(service, 'get_chemical', lambda db, chemical_id: SimpleNamespace(id=chemical_id, cas_no=None))
    with pytest.raises(BusinessValidationError, match='CAS'):
        service.update_chemical(None, 1, ChemicalUpdate(chemical_name='更新'))


def test_api_and_csv_enforce_cas_and_rollback(client, db_session, demo_password):
    from sqlalchemy import select
    from app.modules.system.model import User
    from tests.conftest import login
    from tests.test_batch_api import sample_cas

    admin = db_session.scalar(select(User).where(User.username.in_(['SystemAdmin', 'SystemAdmin'])))
    if admin is None:
        pytest.skip('缺少管理员演示账号')
    headers = login(client, admin.username, demo_password)
    cas = sample_cas()
    created = client.post('/api/v1/chemicals', headers=headers, json={'chemical_name': '校验测试', 'cas_no': cas})
    assert created.status_code == 201, created.text
    chemical_id = created.json()['id']
    assert client.post('/api/v1/chemicals', headers=headers, json={'chemical_name': '缺少CAS'}).status_code == 422
    assert client.patch(f'/api/v1/chemicals/{chemical_id}', headers=headers, json={'cas_no': None}).status_code == 422
    assert client.post('/api/v1/chemicals', headers=headers, json={'chemical_name': '重复CAS', 'cas_no': cas}).status_code == 409
    content = f'chemical_name,cas_no\n导入有效,{sample_cas()}\n导入缺失,\n'.encode('utf-8')
    response = client.post('/api/v1/batch/master.chemicals/import', headers=headers, files={'file': ('data.csv', content, 'text/csv')})
    assert response.status_code == 400
    from app.modules.chemicals.model import Chemical
    assert db_session.scalar(select(Chemical.id).where(Chemical.chemical_name == '导入有效')) is None
