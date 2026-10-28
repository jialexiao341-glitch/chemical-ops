"""批量主数据操作的端到端规则。"""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import login
from app.modules.batch.controller import EXPORT_COLUMNS, RESOURCES


def test_batch_export_columns_are_explicit_and_never_include_auth_secrets() -> None:
    assert set(EXPORT_COLUMNS) == set(RESOURCES)
    forbidden = {"password_hash", "token_version", "avatar", "avatar_base64"}
    for resource_name, columns in EXPORT_COLUMNS.items():
        model_columns = {column.key for column in RESOURCES[resource_name].model.__table__.columns}
        assert set(columns) <= model_columns
        assert not forbidden.intersection(columns)


def test_batch_requires_login(client: TestClient) -> None:
    response = client.post("/api/v1/batch/master.chemicals/delete", json={"ids": [1]})
    assert response.status_code == 401


def test_chemical_batch_disable_and_export(client: TestClient, demo_password: str) -> None:
    headers = login(client, "system_admin", demo_password)
    suffix = uuid4().hex[:12]
    ids = []
    for number in range(2):
        response = client.post(
            "/api/v1/chemicals",
            headers=headers,
            json={"chemical_name": f"批量测试-{suffix}-{number}"},
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])

    exported = client.post(
        "/api/v1/batch/master.chemicals/export", headers=headers, json={"ids": ids}
    )
    assert exported.status_code == 200, exported.text
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert f"批量测试-{suffix}-0" in exported.text

    disabled = client.post(
        "/api/v1/batch/master.chemicals/delete", headers=headers, json={"ids": ids}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"action": "disabled", "count": 2}
    for chemical_id in ids:
        item = client.get(f"/api/v1/chemicals/{chemical_id}", headers=headers)
        assert item.status_code == 200
        assert item.json()["status"] == "INACTIVE"


def test_batch_import_is_atomic_on_invalid_row(client: TestClient, demo_password: str) -> None:
    headers = login(client, "system_admin", demo_password)
    suffix = uuid4().hex[:12]
    name = f"导入测试-{suffix}"
    csv_content = f'chemical_name\n{name}\n""\n'.encode("utf-8")

    response = client.post(
        "/api/v1/batch/master.chemicals/import",
        headers=headers,
        files={"file": ("chemicals.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 400, response.text
    listed = client.get("/api/v1/chemicals", headers=headers, params={"keyword": name})
    assert listed.status_code == 200
    assert listed.json()["total"] == 0


def test_batch_user_disable_rejects_pending_registration_atomically(client: TestClient, db_session, demo_password: str) -> None:
    from sqlalchemy import select
    from app.modules.system.model import User
    user = db_session.scalar(select(User).where(User.username == 'buyer'))
    other = db_session.scalar(select(User).where(User.username == 'warehouse_receiver'))
    if user is None or other is None:
        import pytest
        pytest.skip('缺少采购员演示账号')
    user.status = 'PENDING'
    db_session.flush()
    before = user.token_version
    other_status, other_version = other.status, other.token_version
    response = client.post('/api/v1/batch/system.users/delete', headers=login(client, 'system_admin', demo_password), json={'ids': [user.id, other.id]})
    assert response.status_code == 400, response.text
    db_session.refresh(user)
    assert user.status == 'PENDING' and user.token_version == before
    db_session.refresh(other)
    assert (other.status, other.token_version) == (other_status, other_version)


def test_batch_role_disable_revokes_member_tokens(client: TestClient, db_session, demo_password: str) -> None:
    from sqlalchemy import select
    from app.modules.system.model import Role, User, UserRole
    role = db_session.scalar(select(Role).where(Role.role_code == 'BUYER'))
    assert role is not None
    user = db_session.scalar(select(User).join(UserRole, UserRole.user_id == User.id).where(UserRole.role_id == role.id))
    assert user is not None
    before = user.token_version
    response = client.post('/api/v1/batch/system.roles/delete', headers=login(client, 'system_admin', demo_password), json={'ids': [role.id]})
    assert response.status_code == 200, response.text
    db_session.refresh(user)
    assert user.token_version == before + 1


def test_batch_import_uses_single_create_validation_and_rolls_back(client: TestClient, demo_password: str) -> None:
    headers = login(client, 'system_admin', demo_password)
    suffix = uuid4().hex[:10]
    name = f'批量原子校验-{suffix}'
    cas_no = f'{int(suffix[:6], 16)}-11-1'
    created = client.post('/api/v1/chemicals', headers=headers, json={'chemical_name': f'已有-{suffix}', 'cas_no': cas_no})
    assert created.status_code == 201, created.text
    content = f'chemical_name,cas_no\n{name},\n重复-{suffix},{cas_no}\n'.encode('utf-8')
    response = client.post('/api/v1/batch/master.chemicals/import', headers=headers, files={'file': ('data.csv', content, 'text/csv')})
    assert response.status_code == 409, response.text
    listing = client.get('/api/v1/chemicals', headers=headers, params={'keyword': name})
    assert listing.json()['total'] == 0


def test_batch_import_duplicate_within_file_rolls_back(client: TestClient, demo_password: str) -> None:
    headers = login(client, 'system_admin', demo_password)
    suffix = uuid4().hex[:10]
    name = f'批内重复-{suffix}'
    cas_no = f'{int(suffix[:6], 16)}-12-2'
    content = f'chemical_name,cas_no\n{name},{cas_no}\n另一个-{suffix},{cas_no}\n'.encode('utf-8')
    response = client.post('/api/v1/batch/master.chemicals/import', headers=headers, files={'file': ('data.csv', content, 'text/csv')})
    assert response.status_code == 409, response.text
    listing = client.get('/api/v1/chemicals', headers=headers, params={'keyword': name})
    assert listing.json()['total'] == 0


def test_batch_import_records_audit(client: TestClient, db_session, demo_password: str) -> None:
    from sqlalchemy import select
    from app.modules.chemicals.model import Chemical
    from app.modules.system.audit import AuditLog
    suffix = uuid4().hex[:10]
    name = f'批量审计-{suffix}'
    headers = login(client, 'system_admin', demo_password)
    content = f'chemical_name\n{name}\n'.encode('utf-8')
    response = client.post('/api/v1/batch/master.chemicals/import', headers=headers, files={'file': ('data.csv', content, 'text/csv')})
    assert response.status_code == 200, response.text
    chemical = db_session.scalar(select(Chemical).where(Chemical.chemical_name == name))
    assert chemical is not None
    log = db_session.scalar(select(AuditLog).where(AuditLog.resource_type == 'master.chemicals', AuditLog.resource_id == chemical.id, AuditLog.action_type == 'CREATE'))
    assert log is not None
