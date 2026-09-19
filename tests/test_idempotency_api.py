"""统一 Idempotency-Key 中间件测试。"""

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.modules.system.idempotency_model import IdempotencyRecord

from .conftest import login


pytestmark = pytest.mark.integration


def test_idempotency_key_replays_first_response(client: TestClient, demo_password: str) -> None:
    """同一用户和幂等键重复提交时回放首次响应。"""
    headers = login(client, "system_admin", demo_password)
    headers["Idempotency-Key"] = "TEST-IDEMPOTENCY-READ-ALL"
    first = client.post("/api/v1/notifications/read-all", headers=headers)
    assert first.status_code == 200, first.text
    repeated = client.post("/api/v1/notifications/read-all", headers=headers)
    assert repeated.status_code == first.status_code
    assert repeated.json() == first.json()


def test_idempotency_key_cannot_be_reused_for_a_different_request(client: TestClient, demo_password: str) -> None:
    """同一幂等键用于不同请求体时必须返回冲突。"""

    headers = login(client, "system_admin", demo_password)
    headers["Idempotency-Key"] = "TEST-IDEMPOTENCY-DIFFERENT-BODY"
    first = client.post("/api/v1/notifications/read-all", headers=headers)
    assert first.status_code == 200, first.text
    different = client.post("/api/v1/notifications/read-all", headers={**headers, "Content-Type": "application/json"}, content=b"{}")
    assert different.status_code == 409
    assert "已用于其他请求" in different.json()["detail"]


def test_idempotency_can_be_enabled_as_a_required_policy(client: TestClient, demo_password: str, monkeypatch) -> None:
    """生产策略开启后，未携带幂等键的写请求会被明确拒绝。"""

    from types import SimpleNamespace

    headers = login(client, "system_admin", demo_password)
    monkeypatch.setattr("app.core.idempotency.get_settings", lambda: SimpleNamespace(idempotency_required=True))
    response = client.post("/api/v1/notifications/read-all", headers=headers)
    assert response.status_code == 428
    assert "必须携带 Idempotency-Key" in response.json()["detail"]

def test_expired_idempotency_record_can_be_reused(client: TestClient, demo_password: str) -> None:
    """过期幂等记录会被清理，同一键可以建立新的请求。"""

    headers = login(client, "system_admin", demo_password)
    key = f"TEST-IDEMPOTENCY-EXPIRED-{uuid4().hex}"
    headers["Idempotency-Key"] = key
    actor_key = sha256(headers["Authorization"].encode("utf-8")).hexdigest()
    db = SessionLocal()
    try:
        db.add(
            IdempotencyRecord(
                idempotency_key=key,
                actor_key=actor_key,
                method="POST",
                path="/api/v1/notifications/read-all",
                request_hash=sha256(b"").hexdigest(),
                status="COMPLETED",
                response_status=409,
                response_body={"detail": "过期旧响应"},
                expires_at=datetime.now() - timedelta(minutes=1),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post("/api/v1/notifications/read-all", headers=headers)
    assert response.status_code == 200, response.text