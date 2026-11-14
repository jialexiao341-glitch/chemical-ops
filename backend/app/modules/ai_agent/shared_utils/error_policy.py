"""Agent 错误分类与用户恢复建议，不控制执行或重试。"""

from enum import StrEnum

import httpx


class ErrorClass(StrEnum):
    TRANSIENT_INFRA = "TRANSIENT_INFRA"
    AMBIGUOUS_TIMEOUT = "AMBIGUOUS_TIMEOUT"
    BUSINESS_INVALID = "BUSINESS_INVALID"
    AUTHORIZATION = "AUTHORIZATION"
    FORMAT = "FORMAT"
    BUDGET = "BUDGET"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    UNKNOWN = "UNKNOWN"


class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    NARROW_SCOPE = "NARROW_SCOPE"
    REAUTH = "REAUTH"
    FIX_INPUT = "FIX_INPUT"
    WAIT = "WAIT"
    CONTACT_SUPPORT = "CONTACT_SUPPORT"


_HINTS = {
    RecoveryAction.RETRY: "请稍后重试；如反复失败，请联系管理员。",
    RecoveryAction.NARROW_SCOPE: "请缩小查询范围或拆分任务后重试。",
    RecoveryAction.REAUTH: "请检查登录状态及所需权限，必要时联系管理员。",
    RecoveryAction.FIX_INPUT: "请核对输入和业务条件后重新发起。",
    RecoveryAction.WAIT: "请稍候并核对任务状态，再决定是否重新发起。",
    RecoveryAction.CONTACT_SUPPORT: "请联系管理员检查任务状态。",
}

_MAPPING = {
    **{code: (ErrorClass.BUDGET, RecoveryAction.NARROW_SCOPE) for code in
       ("STEP_LIMIT", "CONTEXT_LIMIT", "TOKEN_BUDGET_EXCEEDED", "TASK_TIMEOUT", "QUOTA_EXCEEDED")},
    **{code: (ErrorClass.BUSINESS_INVALID, RecoveryAction.FIX_INPUT) for code in
       ("INVALID_EVIDENCE", "INCOMPLETE_TASK", "TOOL_ERRORS", "INTENT_MISMATCH", "UNSUPPORTED_REQUEST")},
    "REPEATED_TOOL": (ErrorClass.BUSINESS_INVALID, RecoveryAction.NARROW_SCOPE),
    "TOOL_TIMEOUT": (ErrorClass.TOOL_TIMEOUT, RecoveryAction.NARROW_SCOPE),
    "TOOL_TIMEOUT_UNSUPPORTED": (ErrorClass.TOOL_TIMEOUT, RecoveryAction.CONTACT_SUPPORT),
    "PERMISSION_DENIED": (ErrorClass.AUTHORIZATION, RecoveryAction.REAUTH),
    "MODEL_FORMAT_ERROR": (ErrorClass.FORMAT, RecoveryAction.RETRY),
    "INTENT_SCHEMA_ERROR": (ErrorClass.FORMAT, RecoveryAction.RETRY),
    "DATABASE_ERROR": (ErrorClass.TRANSIENT_INFRA, RecoveryAction.RETRY),
    "MODEL_SERVICE_ERROR": (ErrorClass.TRANSIENT_INFRA, RecoveryAction.WAIT),
    "INTENT_SERVICE_ERROR": (ErrorClass.TRANSIENT_INFRA, RecoveryAction.WAIT),
    "WORKER_UNAVAILABLE": (ErrorClass.TRANSIENT_INFRA, RecoveryAction.WAIT),
}


def _ambiguous(exc: Exception | None) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError)) or "响应超时" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def classify(error_code: str, exc: Exception | None = None) -> tuple[ErrorClass, RecoveryAction, str]:
    """返回分类与固定安全文案；不根据此结果修改重试或业务行为。"""
    # 模型等待期间触发的 TASK_TIMEOUT 与响应阶段断流同属结果未知超时，需按 WAIT 处理。
    if error_code in {"MODEL_SERVICE_ERROR", "INTENT_SERVICE_ERROR", "RUNTIME_ERROR", "TASK_TIMEOUT"} and _ambiguous(exc):
        category, action = ErrorClass.AMBIGUOUS_TIMEOUT, RecoveryAction.WAIT
    else:
        category, action = _MAPPING.get(error_code, (ErrorClass.UNKNOWN, RecoveryAction.CONTACT_SUPPORT))
    return category, action, _HINTS[action]


# 失败阶段只按错误码确定性归因，用于区分“路由/规划/工具/上下文/确认”哪一段先坏；
# 不读取模型输出，也不改变错误分类与重试行为。
_STAGE_BY_CODE = {
    "INTENT_SCHEMA_ERROR": "routing",
    "INTENT_SERVICE_ERROR": "routing",
    "INTENT_MISMATCH": "routing",
    "UNSUPPORTED_REQUEST": "routing",
    "MODEL_FORMAT_ERROR": "planner",
    "MODEL_SERVICE_ERROR": "planner",
    "INVALID_TOOL_REQUEST": "tool",
    "TOOL_ERRORS": "tool",
    "TOOL_TIMEOUT": "tool",
    "TOOL_TIMEOUT_UNSUPPORTED": "tool",
    "REPEATED_TOOL": "tool",
    "PERMISSION_DENIED": "tool",
    "CONTEXT_LIMIT": "context",
    "STEP_LIMIT": "context",
    "TOKEN_BUDGET_EXCEEDED": "budget",
    "QUOTA_EXCEEDED": "budget",
    "TASK_TIMEOUT": "budget",
    "INVALID_EVIDENCE": "confirm",
    "INCOMPLETE_TASK": "confirm",
    "DATABASE_ERROR": "infra",
    "WORKER_UNAVAILABLE": "infra",
    "RUNTIME_ERROR": "infra",
}


def failure_stage(error_code: str | None) -> str:
    """返回首个可确定归因的失败阶段；未知错误码记为 unknown，不猜测业务原因。"""
    if not error_code:
        return "unknown"
    return _STAGE_BY_CODE.get(str(error_code), "unknown")
