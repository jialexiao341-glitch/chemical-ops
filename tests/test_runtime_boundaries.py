"""请求入口的体积限制和审计上下文，不依赖真实代理。"""
import asyncio
import pytest

from app.core.observability import RequestContextMiddleware
from app.modules.system.audit import add_audit_log


def test_chunked_body_limit_without_content_length():
    from app.core.request_limits import RequestBodyLimitMiddleware

    called = []
    async def app(scope, receive, send):
        called.append(True)
    messages = iter([{'type': 'http.request', 'body': b'1234', 'more_body': True},
                     {'type': 'http.request', 'body': b'5678', 'more_body': False}])
    sent = []
    async def receive():
        return next(messages)
    async def send(message):
        sent.append(message)
    asyncio.run(RequestBodyLimitMiddleware(app, json_limit_bytes=7, multipart_limit_bytes=9)(
        {'type': 'http', 'method': 'POST', 'headers': []}, receive, send))
    assert sent[0]['status'] == 413
    assert not called


def test_untrusted_xff_ignored_and_audit_context_reset():
    class DB:
        def add(self, entity):
            pass
    logs = []
    async def app(scope, receive, send):
        logs.append(add_audit_log(DB(), actor_id=None, action_type='TEST', resource_type='TEST',
                                  resource_id=None, request_summary='test', result_status='SUCCESS'))
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})
    async def receive():
        return {'type': 'http.request', 'body': b''}
    async def send(message):
        pass
    asyncio.run(RequestContextMiddleware(app)(
        {'type': 'http', 'method': 'POST', 'client': ('192.0.2.1', 1234),
         'headers': [(b'x-forwarded-for', b'203.0.113.5'), (b'user-agent', b'Boundary test')]}, receive, send))
    assert logs[0].ip_address == '192.0.2.1'
    assert logs[0].user_agent == 'Boundary test'
    outside = add_audit_log(DB(), actor_id=None, action_type='TEST', resource_type='TEST',
                            resource_id=None, request_summary='outside', result_status='SUCCESS')
    assert outside.ip_address is None


def test_rbac_cache_is_request_scoped_and_invalidates_on_role_change(db_session):
    from sqlalchemy import event, select
    from app.core.observability import request_scope_context
    from app.modules.system import crud
    from app.modules.system.model import User

    user = db_session.scalar(select(User).where(User.username == 'buyer'))
    statements = []
    def capture(*args):
        statements.append(args[2])
    connection = db_session.connection()
    event.listen(connection, 'before_cursor_execute', capture)
    token = request_scope_context.set(object())
    try:
        roles = crud.get_user_role_codes(db_session, user.id)
        assert roles
        count = len(statements)
        assert crud.get_user_role_codes(db_session, user.id) == roles
        assert len(statements) == count
        crud.replace_user_roles(db_session, user.id, [])
        assert crud.get_user_role_codes(db_session, user.id) == []
        request_scope_context.set(object())
        count = len(statements)
        assert crud.get_user_role_codes(db_session, user.id) == []
        assert len(statements) == count + 1
    finally:
        request_scope_context.reset(token)
        event.remove(connection, 'before_cursor_execute', capture)


@pytest.mark.parametrize('multipart,limit,size,status', [(False, 4, 4, 200), (False, 4, 5, 413),
                                                       (True, 6, 6, 200), (True, 6, 7, 413)])
def test_body_limit_boundary_and_replay(multipart, limit, size, status):
    from app.core.request_limits import RequestBodyLimitMiddleware
    from starlette.requests import Request
    sent = []
    async def app(scope, receive, send):
        assert await Request(scope, receive).body() == b'x' * size
        await send({'type': 'http.response.start', 'status': 200})
    async def receive():
        return {'type': 'http.request', 'body': b'x' * size}
    async def send(message):
        sent.append(message)
    headers = [(b'content-type', b'multipart/form-data; boundary=a')] if multipart else []
    asyncio.run(RequestBodyLimitMiddleware(app, json_limit_bytes=limit, multipart_limit_bytes=limit)(
        {'type': 'http', 'method': 'POST', 'headers': headers}, receive, send))
    assert sent[0]['status'] == status


def test_disconnected_body_never_calls_application():
    from app.core.request_limits import RequestBodyLimitMiddleware
    async def app(*args):
        pytest.fail('断连请求不能执行写操作')
    async def receive():
        return {'type': 'http.disconnect'}
    asyncio.run(RequestBodyLimitMiddleware(app)({'type': 'http', 'method': 'POST', 'headers': []}, receive, None))


def test_shared_nat_account_lock_isolated(db_session):
    from datetime import datetime, timedelta
    from uuid import uuid4
    from sqlalchemy import text
    from app.modules.system import service

    ip = f'nat-{uuid4().hex}'
    now = datetime.now()
    scopes, _ = service._lock_login_scopes(db_session, 'first-account', ip, now)
    own = service._login_scope_key('account_ip', f'first-account\0{ip}')
    db_session.execute(text('UPDATE sys_login_attempts SET failure_count=5, locked_until=:until WHERE scope_key=:key'),
                       {'until': now + timedelta(minutes=10), 'key': own})
    other_scopes, other = service._lock_login_scopes(db_session, 'second-account', ip, now)
    assert own not in other
    assert len(set(scopes) & set(other_scopes)) == 1
    assert all(row['locked_until'] is None for row in other.values())
