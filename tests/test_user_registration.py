"""公开注册与管理员审批的身份和权限边界。"""

from uuid import uuid4
import base64

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.system.model import Role, User, UserRole
from app.modules.system.audit import AuditLog
from .conftest import login

pytestmark = pytest.mark.integration


def payload(demo_password, role_code="BUYER"):
    return {"username": f"UserA{uuid4().hex[:8]}", "password": "RegPass12",
            "display_name": "苏亦宁", "role_code": role_code}


def test_registration_requires_approval_then_can_login(client, db_session, demo_password):
    data = payload(demo_password)
    image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jQqkAAAAASUVORK5CYII=')
    data['avatar_base64'] = 'data:image/png;base64,' + base64.b64encode(image).decode()
    roles = client.get('/api/v1/auth/registration-roles')
    assert roles.status_code == 200
    assert all(set(role) == {"role_code", "role_name"} and role["role_code"] != "SYS_ADMIN" for role in roles.json())
    assert "BUYER" in {role["role_code"] for role in roles.json()}
    registered = client.post('/api/v1/auth/register', json=data)
    assert registered.status_code == 201, registered.text
    assert registered.json() == {"username": data['username'], "status": 'PENDING'}
    user = db_session.scalar(select(User).where(User.username == data['username']))
    assert user.avatar == image
    before = client.post('/api/v1/auth/login', json={k: data[k] for k in ('username','password')})
    assert before.status_code == 401 and '待管理员审批' in before.json()['detail']
    forged = {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}
    assert client.get('/api/v1/auth/me', headers=forged).status_code == 401
    admin = login(client, 'system_admin', demo_password)
    listing = client.get('/api/v1/system/users', headers=admin, params={'status':'PENDING', 'keyword':data['username']})
    assert listing.status_code == 200
    assert listing.json()['items'][0]['role_codes'] == ['BUYER']
    assert listing.json()['items'][0]['role_names']
    path = f'/api/v1/system/users/{user.id}'
    assert client.patch(path, headers=admin, json={'status':'ACTIVE'}).status_code == 400
    assert client.delete(path, headers=admin).status_code == 400
    reviewed = client.post(path+'/registration-review', headers=admin, json={'decision':'approve','reason':'身份已核实'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['status'] == 'ACTIVE'
    approved = client.post('/api/v1/auth/login', json={k:data[k] for k in ('username','password')})
    assert approved.status_code == 200, approved.text
    headers = {"Authorization": f"Bearer {approved.json()['access_token']}"}
    profile = client.get('/api/v1/auth/me', headers=headers).json()
    assert profile['role_codes'] == ['BUYER']
    assert profile['avatar'] == data['avatar_base64']
    assert client.post(path+'/registration-review', headers=admin, json={'decision':'approve'}).status_code == 400
    assert db_session.scalar(select(AuditLog).where(AuditLog.resource_id==user.id, AuditLog.action_type=='REVIEW_REGISTRATION')) is not None


def test_registration_reject_and_no_review_bypass(client, db_session, demo_password):
    data = payload(demo_password, 'SUPPLIER_PORTAL')
    assert client.post('/api/v1/auth/register', json=data).status_code == 201
    user = db_session.scalar(select(User).where(User.username==data['username']))
    path = f'/api/v1/system/users/{user.id}'
    buyer = login(client, 'buyer', demo_password)
    assert client.post(path+'/registration-review', headers=buyer, json={'decision':'approve'}).status_code == 403
    assert client.post(path+'/registration-review', json={'decision':'approve'}).status_code == 401
    admin = login(client, 'system_admin', demo_password)
    assert client.post(path+'/registration-review', headers=admin, json={'decision':'reject','reason':'信息不完整'}).json()['status'] == 'REJECTED'
    assert client.patch(path, headers=admin, json={'status':'ACTIVE'}).status_code == 400
    assert client.delete(path, headers=admin).status_code == 400
    refused = client.post('/api/v1/auth/login', json={k:data[k] for k in ('username','password')})
    assert refused.status_code == 401 and '已被拒绝' in refused.json()['detail']


def test_registration_forbids_admin_extra_fields_duplicates_and_disabled_roles(client, db_session, demo_password):
    data = payload(demo_password, 'SYS_ADMIN')
    assert client.post('/api/v1/auth/register', json=data).status_code == 400
    data['role_code'] = 'BUYER'
    for extra in [{'status':'ACTIVE'}, {'role_ids':[1]}, {'department_id':1}]:
        assert client.post('/api/v1/auth/register', json={**data, **extra}).status_code == 422
    assert client.post('/api/v1/auth/register', json={**data,'password':'short'}).status_code == 422
    assert client.post('/api/v1/auth/register', json={**data,'display_name':'   '}).status_code == 400
    role = Role(role_code=f'REG_{uuid4().hex[:10]}', role_name='停用角色', status='INACTIVE')
    db_session.add(role)
    db_session.flush()
    assert client.post('/api/v1/auth/register', json={**data,'role_code':role.role_code}).status_code == 400
    assert client.post('/api/v1/auth/register', json=data).status_code == 201
    assert client.post('/api/v1/auth/register', json=data).status_code == 409


def test_role_expiry_prevents_registration_approval(client, db_session, demo_password):
    role = Role(role_code=f'REG_{uuid4().hex[:10]}', role_name='测试角色', status='ACTIVE')
    db_session.add(role)
    db_session.flush()
    data = payload(demo_password, role.role_code)
    assert client.post('/api/v1/auth/register', json=data).status_code == 201
    user = db_session.scalar(select(User).where(User.username==data['username']))
    role.status='INACTIVE'
    db_session.flush()
    admin = login(client, 'system_admin', demo_password)
    assert client.post(f'/api/v1/system/users/{user.id}/registration-review',headers=admin,json={'decision':'approve'}).status_code==400


@pytest.mark.parametrize('field,value', [
    ('username', 'Abcdef1'), ('username', 'Abcdefghijklmnop1'),
    ('username', 'lowercase1'), ('username', 'UPPERCASE1'), ('username', 'Account-1'),
    ('password', 'Abcdef1'), ('password', 'Abcdefghijklmnop1'),
    ('password', 'lowercase1'), ('password', 'UPPERCASE1'),
])
def test_registration_rejects_invalid_account_and_password(client, db_session, demo_password, field, value):
    data = {**payload(demo_password), field: value}
    assert client.post('/api/v1/auth/register', json=data).status_code == 422
    assert db_session.scalar(select(User.id).where(User.username == data['username'])) is None


@pytest.mark.parametrize('length', [8, 16])
def test_registration_accepts_credential_length_boundaries(client, demo_password, length):
    data = payload(demo_password)
    data['username'] = 'Aa' + uuid4().hex[:length-2]
    data['password'] = 'Aa' + '1' * (length-2)
    assert client.post('/api/v1/auth/register', json=data).status_code == 201


@pytest.mark.parametrize('avatar', ['not-base64', base64.b64encode(b'not an image').decode(),
                                    base64.b64encode(b'\x89PNG' + b'x' * (512 * 1024)).decode()],
                         ids=['malformed-base64', 'not-image', 'oversized-image'])
def test_registration_rejects_invalid_avatar(client, db_session, demo_password, avatar):
    data = {**payload(demo_password), 'avatar_base64': avatar}
    assert client.post('/api/v1/auth/register', json=data).status_code == 400
    assert db_session.scalar(select(User.id).where(User.username == data['username'])) is None
