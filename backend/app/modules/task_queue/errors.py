"""Classify transport failures without storing exception messages or credentials."""

import httpx
from sqlalchemy.exc import OperationalError

# 只有“请求尚未建立”或数据库连接类错误可安全重放。
# 读超时、读/写中断等可能已在上游开始生成或计费，交给调用方按模型错误处理。
_SAFE_RETRY_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    ConnectionError,
    OperationalError,
)


def transient(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, _SAFE_RETRY_ERRORS):
            return True
        if isinstance(error, httpx.HTTPStatusError) and (
                error.response.status_code == 429 or error.response.status_code >= 500):
            return True
        error = error.__cause__
    return False
