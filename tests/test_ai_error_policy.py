"""错误分类只提供建议，不控制实际重试。"""

import httpx
import pytest

from app.modules.ai.error_policy import ErrorClass, RecoveryAction, classify


@pytest.mark.parametrize(("code", "category", "action"), [
    ("STEP_LIMIT", "BUDGET", "NARROW_SCOPE"), ("CONTEXT_LIMIT", "BUDGET", "NARROW_SCOPE"),
    ("INVALID_EVIDENCE", "BUSINESS_INVALID", "FIX_INPUT"), ("INCOMPLETE_TASK", "BUSINESS_INVALID", "FIX_INPUT"),
    ("REPEATED_TOOL", "BUSINESS_INVALID", "NARROW_SCOPE"), ("TOOL_ERRORS", "BUSINESS_INVALID", "FIX_INPUT"),
    ("INTENT_MISMATCH", "BUSINESS_INVALID", "FIX_INPUT"), ("TOKEN_BUDGET_EXCEEDED", "BUDGET", "NARROW_SCOPE"),
    ("QUOTA_EXCEEDED", "BUDGET", "NARROW_SCOPE"),
    ("TOOL_TIMEOUT", "TOOL_TIMEOUT", "NARROW_SCOPE"), ("TOOL_TIMEOUT_UNSUPPORTED", "TOOL_TIMEOUT", "CONTACT_SUPPORT"),
    ("TASK_TIMEOUT", "BUDGET", "NARROW_SCOPE"), ("PERMISSION_DENIED", "AUTHORIZATION", "REAUTH"),
    ("MODEL_FORMAT_ERROR", "FORMAT", "RETRY"), ("DATABASE_ERROR", "TRANSIENT_INFRA", "RETRY"),
    ("MODEL_SERVICE_ERROR", "TRANSIENT_INFRA", "WAIT"), ("RUNTIME_ERROR", "UNKNOWN", "CONTACT_SUPPORT"),
    ("UNSUPPORTED_REQUEST", "BUSINESS_INVALID", "FIX_INPUT"),
])
def test_declared_error_mapping(code, category, action):
    error_class, recovery, hint = classify(code)
    assert error_class == ErrorClass(category)
    assert recovery == RecoveryAction(action)
    assert hint


@pytest.mark.parametrize("exception", [httpx.ReadTimeout("private"), httpx.WriteTimeout("private"),
    httpx.RemoteProtocolError("private"), ValueError("AI 服务响应超时，请稍后重试")])
def test_ambiguous_response_failures_advise_wait(exception):
    error_class, action, hint = classify("MODEL_SERVICE_ERROR", exception)
    assert (error_class, action) == (ErrorClass.AMBIGUOUS_TIMEOUT, RecoveryAction.WAIT)
    assert "private" not in hint


@pytest.mark.parametrize("exception", [httpx.ConnectError("private"),
    httpx.HTTPStatusError("private", request=httpx.Request("GET", "https://example.test"),
                          response=httpx.Response(429))])
def test_infrastructure_failures_have_advisory_classification(exception):
    assert classify("MODEL_SERVICE_ERROR", exception)[:2] == (ErrorClass.TRANSIENT_INFRA, RecoveryAction.WAIT)


def test_intent_connection_failure_is_transient_infrastructure():
    assert classify("INTENT_SERVICE_ERROR", httpx.ConnectError("private"))[:2] == (
        ErrorClass.TRANSIENT_INFRA, RecoveryAction.WAIT)


def test_wrapped_timeout_is_detected():
    cause = httpx.ReadTimeout("private")
    error = ValueError("outer")
    error.__cause__ = cause
    assert classify("INTENT_SERVICE_ERROR", error)[:2] == (ErrorClass.AMBIGUOUS_TIMEOUT, RecoveryAction.WAIT)


def test_unknown_error_is_safe_and_does_not_expose_exception():
    category, action, hint = classify("unexpected", ValueError("secret"))
    assert (category, action) == (ErrorClass.UNKNOWN, RecoveryAction.CONTACT_SUPPORT)
    assert "secret" not in hint
