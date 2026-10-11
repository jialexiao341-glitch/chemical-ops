"""用户级固定窗口限流：Lua 原子计数，跨进程共享同一配额。"""

from math import ceil

from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.observability import metrics
from app.core.redis_client import get_redis, redis_key
from app.modules.system.model import User


# 窗口从首次获准请求起算；拒绝请求不续期、不消耗额外计数。
LIMIT_SCRIPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('PTTL', KEYS[1])
if count >= tonumber(ARGV[1]) then
    return {0, math.max(ttl, 1)}
end
count = redis.call('INCR', KEYS[1])
if count == 1 or ttl < 0 then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    ttl = tonumber(ARGV[2])
end
return {1, ttl}
"""


def check_limit(user_id: int, category: str) -> None:
    settings = get_settings()
    if not settings.redis_rate_limit_enabled:
        return
    limit = settings.ai_rate_limit_requests if category == "ai" else settings.document_rate_limit_requests
    client = get_redis()
    try:
        if client is None:
            raise RedisError("Redis is disabled")
        allowed, ttl = client.eval(LIMIT_SCRIPT, 1, redis_key("limit", category, user_id),
                                   limit, settings.rate_limit_window_seconds * 1000)
    except RedisError:
        metrics.increment("rate_limit", labels={"category": category, "result": "unavailable"})
        raise HTTPException(503, "请求保护服务暂时不可用，请稍后重试", headers={"Retry-After": "1"}) from None
    metrics.increment("rate_limit", labels={"category": category, "result": "allowed" if allowed else "rejected"})
    if not allowed:
        raise HTTPException(429, "请求过于频繁，请稍后重试", headers={"Retry-After": str(max(1, ceil(ttl / 1000)))})


def limit_ai(request: Request, user: User = Depends(get_current_user)) -> None:
    # 任务读取、取消和会话管理不消耗模型请求配额。
    if request.method == "POST" and not request.url.path.endswith("/cancel"):
        check_limit(user.id, "ai")


def limit_document(user: User = Depends(get_current_user)) -> None:
    check_limit(user.id, "document")
