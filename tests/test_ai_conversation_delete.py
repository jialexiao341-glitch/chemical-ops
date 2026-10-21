from fastapi.testclient import TestClient
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select

from app.modules.ai.model import AIAgentTask, AIPurchaseDraftConfirmation, AIConversation, AIMessage
from app.modules.ai.conversation_store import delete_conversation
from app.modules.task_queue.model import TaskExecution, TaskResourceLock
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


def test_manage_own_ai_conversation(client: TestClient, db_session, demo_password: str) -> None:
    user = get_user_by_username(db_session, "system_admin")
    assert user is not None
    conversation = AIConversation(user_id=user.id, title="原会话", business_scene="GENERAL", permission_snapshot={}, status="ACTIVE")
    db_session.add(conversation)
    db_session.flush()
    headers = _login(client, demo_password)

    response = client.patch(f"/api/v1/ai/conversations/{conversation.id}", json={"title": "  库存追溯  ", "pinned": True}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "库存追溯"
    assert response.json()["pinned"] is True

    listed = client.get("/api/v1/ai/conversations?limit=100", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == conversation.id and item["pinned"] for item in listed.json()["items"])

    invalid = client.patch(f"/api/v1/ai/conversations/{conversation.id}", json={"title": "  "}, headers=headers)
    assert invalid.status_code == 400

    missing = client.patch("/api/v1/ai/conversations/999999999", json={"pinned": True}, headers=headers)
    assert missing.status_code == 400


def test_delete_conversation_cancels_owned_running_tasks_and_draft(db_session):
    from types import SimpleNamespace
    from app.modules.ai import conversation_store
    from app.modules.purchase_requests.model import PurchaseRequest

    from app.modules.system.model import User
    user = db_session.scalar(select(User).where(User.username == 'system_admin'))
    conversation = AIConversation(user_id=user.id, title='生命周期回归', business_scene='GENERAL', permission_snapshot={}, status='ACTIVE')
    db_session.add(conversation); db_session.flush()
    task_id = uuid4().hex
    task = AIAgentTask(id=task_id, user_id=user.id, status='RUNNING', revision=3,
        payload={'chat': {'conversation_id': conversation.id}, 'trace': [], 'messages': ['private']}, reply='私有轨迹',
        created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db_session.add(task); db_session.flush()
    execution = TaskExecution(id=uuid4().hex, task_type='agent.run', business_id=task_id, actor_id=user.id,
        run_generation=1, business_revision=3, payload={}, checkpoint={}, status='RUNNING', fencing_token=4,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db_session.add(execution); db_session.flush()
    lock = TaskResourceLock(resource_key=f'agent:{task_id}', execution_id=execution.id)
    db_session.add(lock)
    confirmation = AIPurchaseDraftConfirmation(confirmation_id=uuid4().hex, user_id=user.id, preview_version=1,
        request_hash='a'*64, draft_payload={}, object_versions={}, evidence=[{'type': 'conversation', 'conversation_id': conversation.id}],
        status='PENDING', expires_at=datetime(2999, 1, 1))
    db_session.add(confirmation); db_session.flush()
    created = PurchaseRequest(request_no=f'LIFECYCLE-{uuid4().hex[:10]}', applicant_id=user.id,
        department_id=user.department_id, purpose='已创建业务申请', status='DRAFT')
    db_session.add(created); db_session.flush()
    conversation_store.delete_conversation(db_session, user, conversation.id)
    assert db_session.get(AIAgentTask, task_id).status == 'CANCELLED'
    assert db_session.get(AIAgentTask, task_id).revision == 4
    assert db_session.get(AIAgentTask, task_id).payload['chat'] is None
    assert db_session.get(TaskExecution, execution.id).status == 'CANCELLED'
    assert db_session.get(TaskExecution, execution.id).fencing_token == 5
    assert db_session.get(TaskResourceLock, lock.resource_key) is None
    assert db_session.get(AIPurchaseDraftConfirmation, confirmation.id).status == 'CANCELLED'
    assert db_session.get(PurchaseRequest, created.id) is not None
