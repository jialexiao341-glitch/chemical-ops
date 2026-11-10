"""队列重试分类：只重放尚未建立连接的错误，不重放可能已生成的模型响应。"""

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.modules.task_queue.errors import transient


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def _status(code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "upstream failed",
        request=_request(),
        response=httpx.Response(code, request=_request()),
    )


@pytest.mark.parametrize("error", [
    httpx.ConnectError("connect failed", request=_request()),
    httpx.ConnectTimeout("connect timeout", request=_request()),
    httpx.PoolTimeout("pool timeout", request=_request()),
    ConnectionError("connection reset before request"),
    OperationalError("SELECT 1", {}, Exception("database unavailable")),
])
def test_connection_errors_are_retryable(error):
    assert transient(error) is True


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("response timed out", request=_request()),
    httpx.ReadError("stream interrupted", request=_request()),
    httpx.RemoteProtocolError("peer closed connection", request=_request()),
    httpx.WriteError("request body interrupted", request=_request()),
])
def test_response_phase_transport_errors_are_not_retryable(error):
    assert transient(error) is False


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retryable_status_codes(code):
    assert transient(_status(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_non_retryable_status_codes(code):
    assert transient(_status(code)) is False


def test_wrapped_cause_is_classified_not_the_outer_exception():
    wrapped_connect = RuntimeError("wrapper")
    wrapped_connect.__cause__ = httpx.ConnectError("connect failed", request=_request())
    assert transient(wrapped_connect) is True

    wrapped_read = RuntimeError("wrapper")
    wrapped_read.__cause__ = httpx.ReadTimeout("response timed out", request=_request())
    assert transient(wrapped_read) is False
    assert transient(None) is False
