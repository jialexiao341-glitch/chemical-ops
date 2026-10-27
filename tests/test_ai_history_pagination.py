from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.modules.ai.conversation_store import _load_messages


def test_history_paginates_backwards_without_losing_chronological_order():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ai_messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, message_role TEXT, content TEXT, citations JSON, created_at DATETIME)')
        for message_id in range(1, 6):
            connection.exec_driver_sql("INSERT INTO ai_messages VALUES (?, 1, 'USER', ?, NULL, '2026-01-01 00:00:00')", (message_id, str(message_id)))
    with Session(engine) as db:
        latest = _load_messages(db, 1, 2)
        assert [item.id for item in latest.items] == [4, 5] and latest.total == 5
        earlier = _load_messages(db, 1, 2, before_id=4)
        assert [item.id for item in earlier.items] == [2, 3] and earlier.total == 5
    engine.dispose()


def test_history_page_api_is_owned_and_preserves_messages(client, db_session):
    from sqlalchemy import select
    from app.core.auth import get_current_user
    from app.main import app
    from app.modules.ai.model import AIConversation, AIMessage
    from app.modules.system.model import User
    from types import SimpleNamespace
    db = db_session
    owner = db.scalar(select(User).where(User.username == 'system_admin'))
    conversation = AIConversation(user_id=owner.id, title='分页测试', business_scene='GENERAL', permission_snapshot={}, status='ACTIVE')
    db.add(conversation); db.flush()
    for i in range(5):
        db.add(AIMessage(conversation_id=conversation.id, message_role='USER', content=str(i)))
    db.flush()
    current = {'user': owner}
    app.dependency_overrides[get_current_user] = lambda: current['user']
    try:
        latest = client.get(f'/api/v1/ai/conversations/{conversation.id}/messages', params={'limit': 2})
        assert latest.status_code == 200
        page = latest.json()
        assert [item['content'] for item in page['items']] == ['3', '4'] and page['total'] == 5
        previous = client.get(f'/api/v1/ai/conversations/{conversation.id}/messages', params={'limit': 2, 'before_id': page['items'][0]['id']})
        assert [item['content'] for item in previous.json()['items']] == ['1', '2']
        assert len(db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation.id)).all()) == 5
        current['user'] = SimpleNamespace(id=-1)
        assert client.get(f'/api/v1/ai/conversations/{conversation.id}/messages', params={'before_id': page['items'][0]['id']}).status_code in (400, 403, 404)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
