"""个人中心接口测试：资料更新与自助改密码（真实库 + 事务回滚）。"""

from fastapi.testclient import TestClient


def _login(client: TestClient, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system_admin", "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_me_requires_login(client: TestClient):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_patch_me_updates_profile(client: TestClient, demo_password: str):
    headers = _login(client, demo_password)

    response = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"display_name": "测试昵称", "email": "profile@test.local", "phone": "13800000000"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "测试昵称"
    assert body["email"] == "profile@test.local"
    # GET /me 同步可见
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["display_name"] == "测试昵称"


def test_patch_me_rejects_empty_body(client: TestClient, demo_password: str):
    headers = _login(client, demo_password)

    response = client.patch("/api/v1/auth/me", headers=headers, json={})

    assert response.status_code == 400, response.text
    assert "没有需要更新的字段" in response.json()["detail"]


def test_patch_me_ignores_roles_and_status(client: TestClient, demo_password: str):
    """schema 白名单之外的字段（角色/状态）被静默丢弃，不能借个人接口越权。"""

    headers = _login(client, demo_password)
    before = client.get("/api/v1/auth/me", headers=headers).json()

    response = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"display_name": "越权测试", "status": "LOCKED", "role_ids": [999]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "越权测试"
    # 角色与状态保持原样
    assert body["status"] == before["status"] != "LOCKED"
    assert body["role_codes"] == before["role_codes"]
    assert body["role_codes"] != ["999"] and 999 not in body["role_codes"]


def test_change_password_rejects_wrong_old(client: TestClient, demo_password: str):
    headers = _login(client, demo_password)

    response = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": "definitely-wrong", "new_password": "NewPass123"},
    )

    assert response.status_code == 400, response.text
    assert "原密码不正确" in response.json()["detail"]


def test_change_password_rejects_same_password(client: TestClient, demo_password: str):
    headers = _login(client, demo_password)

    response = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": demo_password, "new_password": demo_password},
    )

    assert response.status_code == 400, response.text
    assert "不能与原密码相同" in response.json()["detail"]


def test_change_password_short_new_rejected_by_schema(client: TestClient, demo_password: str):
    headers = _login(client, demo_password)

    response = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": demo_password, "new_password": "short"},
    )

    assert response.status_code == 422, response.text


def test_change_password_success_then_login_with_new(
    client: TestClient, demo_password: str
):
    """改密成功后旧密码失效、新密码可登录；测试事务回滚后原状恢复。"""

    headers = _login(client, demo_password)

    response = client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"old_password": demo_password, "new_password": "NewPass123"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"changed": True}

    # 新密码可登录
    ok = client.post(
        "/api/v1/auth/login",
        json={"username": "system_admin", "password": "NewPass123"},
    )
    assert ok.status_code == 200, ok.text

    # 同一事务内旧密码此时失效（login 走同一会话读到新哈希）
    stale = client.post(
        "/api/v1/auth/login",
        json={"username": "system_admin", "password": demo_password},
    )
    assert stale.status_code == 401, stale.text
