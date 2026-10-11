"""共享 Redis 连接池；缓存与限流共用配置，不记录连接密钥。"""

from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


@lru_cache(maxsize=4)
def _pool(url: str, timeout: float) -> Redis:
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=timeout,
                          socket_timeout=timeout, retry_on_timeout=False, max_connections=32)


def get_redis() -> Redis | None:
    settings = get_settings()
    return _pool(settings.redis_url, settings.redis_timeout_seconds) if settings.redis_enabled else None


def redis_key(*parts: object) -> str:
    settings = get_settings()
    return ":".join((settings.redis_key_prefix, settings.app_env, "v1", *(str(part) for part in parts)))
