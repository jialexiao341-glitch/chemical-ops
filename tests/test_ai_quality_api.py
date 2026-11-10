"""质量聚合接口：仅管理员可读，非法筛选在进入查询前拒绝。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_quality_summary_requires_admin(monkeypatch):
    from app.main import app
    from app.core.auth import get_current_user
    from app.core.db import get_db
    from app.core.rate_limit import limit_ai
    from app.modules.system import crud
    from app.modules.ai import quality_report
    from app.modules.ai import controller as ai_controller

    user = SimpleNamespace(id=1)
    permissions = {"ai.workspace.read"}
    roles = []
    captured = {}

    def summary(_db, **kwargs):
        captured.update(kwargs)
        return {
            "generated_at": "2026-11-10T00:00:00",
            "days": kwargs["days"],
            "tasks": 0,
            "failed_tasks": 0,
            "feedback": 0,
            "up": 0,
            "down": 0,
        }

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[limit_ai] = lambda: None
    monkeypatch.setattr(crud, "get_user_role_codes", lambda *args: list(roles))
    monkeypatch.setattr(crud, "get_user_permission_codes", lambda *args: list(permissions))
    monkeypatch.setattr(ai_controller, "get_user_role_codes", lambda *args: list(roles))
    monkeypatch.setattr(quality_report, "summarize", summary)
    try:
        client = TestClient(app)
        assert client.get("/api/v1/ai/quality/summary").status_code == 403

        roles.append("SYS_ADMIN")
        response = client.get("/api/v1/ai/quality/summary", params={
            "days": 7, "prompt_version": "planner@1-aaa",
            "error_class": "BUSINESS_INVALID", "tool": "inventory.query_available",
            "rating": "DOWN",
        })
        assert response.status_code == 200, response.text
        assert response.json()["down"] == 0
        assert captured["prompt_version"] == "planner@1-aaa"
        assert captured["rating"] == "DOWN"

        assert client.get("/api/v1/ai/quality/summary", params={"rating": "BAD"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
