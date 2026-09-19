from fastapi.testclient import TestClient

from app.modules.ai.model import AIConversation, AIMessage
from app.modules.system.crud import get_user_by_username


def _login(client: TestClient, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": "system_admin", "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_delete_own_ai_conversation_removes_messages(client: TestClient, db_session, demo_password: str) -> None:
    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    conversation = AIConversation(user_id=user.id, title="待删除会话", business_scene="GENERAL", permission_snapshot={}, status="ACTIVE")
    db_session.add(conversation)
    db_session.flush()
    db_session.add(AIMessage(conversation_id=conversation.id, message_role="USER", content="测试消息"))
    db_session.flush()

    response = client.delete(f"/api/v1/ai/conversations/{conversation.id}", headers=_login(client, demo_password))

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
    assert db_session.get(AIConversation, conversation.id) is None
    assert db_session.query(AIMessage).filter(AIMessage.conversation_id == conversation.id).count() == 0
