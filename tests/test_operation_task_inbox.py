"""异常任务跨用户待办与通知，使用事务回滚且不触发登录。"""
from uuid import uuid4
from sqlalchemy import select
from app.core.auth import get_current_user
from app.main import app
from app.modules.notifications.model import Notification
from app.modules.operation_exceptions.model import OperationException
from app.modules.system.model import User


def test_assigned_task_inbox_reassignment_and_notification(client, db_session):
    users = {name: db_session.scalar(select(User).where(User.username == name))
             for name in ('system_admin', 'buyer', 'procurement_manager')}
    current = {'user': users['system_admin']}
    app.dependency_overrides[get_current_user] = lambda: current['user']
    exc = OperationException(exception_no='TASK-'+uuid4().hex[:12], exception_type='OTHER',
        source_type='OTHER', source_id=9876, owner_id=users['system_admin'].id,
        severity='MEDIUM', description='验收异常', status='OPEN')
    db_session.add(exc); db_session.flush()
    try:
        response = client.post(f'/api/v1/operation-exceptions/{exc.id}/tasks', json={
            'title': '核查业务情况', 'assignee_id': users['buyer'].id, 'priority': 'HIGH'})
        assert response.status_code == 201, response.text
        task_id = response.json()['id']
        notices = list(db_session.scalars(select(Notification).where(
            Notification.notification_type == 'OPERATION_TASK_ASSIGNED', Notification.related_id == task_id)).all())
        assert len(notices) == 1 and notices[0].recipient_id == users['buyer'].id
        assert '核查业务情况' not in notices[0].content
        current['user'] = users['buyer']
        page = client.get('/api/v1/operation-exceptions/my-tasks').json()
        assert any(item['id'] == task_id and item['exception_no'] == exc.exception_no for item in page['items'])
        assert client.get(f'/api/v1/operation-exceptions/my-tasks/{task_id}').status_code == 200
        url = f'/api/v1/notifications/{notices[0].id}/operation-task'
        assert client.get(url).json() == {'exception_id': exc.id, 'task_id': task_id}
        assert client.patch(f'/api/v1/operation-exceptions/{exc.id}/tasks/{task_id}', json={'status': 'PROCESSING'}).status_code == 403
        current['user'] = users['system_admin']
        assert client.patch(f'/api/v1/operation-exceptions/{exc.id}/tasks/{task_id}', json={'assignee_id': users['procurement_manager'].id}).status_code == 200
        assert client.patch(f'/api/v1/operation-exceptions/{exc.id}/tasks/{task_id}', json={'assignee_id': users['procurement_manager'].id}).status_code == 200
        notices = list(db_session.scalars(select(Notification).where(Notification.notification_type == 'OPERATION_TASK_ASSIGNED', Notification.related_id == task_id).order_by(Notification.id)).all())
        assert len(notices) == 2 and notices[1].recipient_id == users['procurement_manager'].id
        current['user'] = users['buyer']
        assert client.get(url).status_code == 404
        assert client.get(f'/api/v1/operation-exceptions/my-tasks/{task_id}').status_code == 404
        assert not any(item['id'] == task_id for item in client.get('/api/v1/operation-exceptions/my-tasks').json()['items'])
        current['user'] = users['procurement_manager']
        assert client.get(f'/api/v1/notifications/{notices[1].id}/operation-task').status_code == 200
        assert client.get(f'/api/v1/operation-exceptions/my-tasks/{task_id}').status_code == 200
        assert client.patch(f'/api/v1/operation-exceptions/{exc.id}/tasks/{task_id}', json={'status': 'PROCESSING'}).status_code == 200
        assert client.patch(f'/api/v1/operation-exceptions/{exc.id}/tasks/{task_id}', json={'status': 'COMPLETED', 'completion_note': '已核查'}).status_code == 200
        assert not any(item['id'] == task_id for item in client.get('/api/v1/operation-exceptions/my-tasks').json()['items'])
        assert any(item['id'] == task_id for item in client.get('/api/v1/operation-exceptions/my-tasks', params={'status': 'ALL'}).json()['items'])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
