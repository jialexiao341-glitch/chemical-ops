"""服务层和 API 异常处理器共用的业务异常。"""

from typing import Any

from pydantic import BaseModel


class ApiError(BaseModel):
    """返回给前端的统一错误响应。"""

    code: int
    message: str
    detail: Any = None


STATUS_MESSAGES = {
    400: "请求不符合业务规则",
    401: "认证失败",
    403: "无权访问",
    404: "资源不存在",
    405: "请求方法不允许",
    409: "数据已存在",
    415: "请求格式不支持",
    422: "请求参数校验失败",
    428: "请求条件不满足",
    500: "服务器内部错误",
}


API_ERROR_RESPONSES = {
    code: {"description": message, "model": ApiError}
    for code, message in STATUS_MESSAGES.items()
    if code in {400, 401, 403, 404, 405, 409, 415, 422, 428, 500}
}


class ResourceNotFoundError(Exception):
    """请求的资源不存在时抛出。"""


class AuthorizationError(Exception):
    """当前用户没有访问目标业务范围的资格。"""


class DuplicateResourceError(Exception):
    """唯一业务字段已经被占用时抛出。"""


class BusinessValidationError(Exception):
    """业务参数不满足规则时抛出。"""


class AuthenticationError(Exception):
    """登录凭据不正确时抛出。"""
