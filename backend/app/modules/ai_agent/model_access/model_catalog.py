"""数据库模型目录的进程内缓存。

数据库中的模型配置是前端「模型管理」的唯一数据源；API 进程与任务 Worker
通过短 TTL 缓存读取，写入后调用 invalidate 立即生效，其他进程最多 15 秒内跟随。
未调用 activate() 的进程（例如单元测试）继续使用环境变量中的单模型配置。
"""

from __future__ import annotations

import logging
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.ai_agent.model_access.gateway import ModelProfileConfig


LOGGER = logging.getLogger("chemicalops.ai.model_catalog")
CACHE_TTL_SECONDS = 15.0

_lock = Lock()
_active = False
_loaded_at = 0.0
_snapshot: tuple[dict[str, ModelProfileConfig], str | None] | None = None


def activate() -> None:
    """允许当前进程从数据库解析模型目录。"""

    global _active
    _active = True
    invalidate()


def deactivate() -> None:
    """仅用于测试：恢复为只读环境变量配置。"""

    global _active
    _active = False
    invalidate()


def invalidate() -> None:
    """丢弃缓存，下一次解析时重新读取数据库。"""

    global _snapshot, _loaded_at
    with _lock:
        _snapshot = None
        _loaded_at = 0.0


def _load_from_database() -> tuple[dict[str, ModelProfileConfig], str | None]:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.ai_agent.model_access.gateway import ModelProfileConfig
    from app.modules.ai_agent.model import AIModelProfile

    with SessionLocal() as db:
        rows = list(db.scalars(select(AIModelProfile).order_by(AIModelProfile.id)).all())

    profiles: dict[str, ModelProfileConfig] = {}
    default_name: str | None = None
    for row in rows:
        profiles[row.profile_name] = ModelProfileConfig(
            provider="openai_compatible",
            model=row.model,
            fallback_profile=None,
            base_url=row.base_url,
            api_key=row.api_key,
            timeout_seconds=float(row.timeout_seconds),
            max_retries=row.max_retries,
            max_concurrency=row.max_concurrency,
            temperature=float(row.temperature),
            max_tokens=row.max_tokens,
            stream_usage=bool(row.stream_usage),
            reasoning_effort=row.reasoning_effort,
        )
        if row.is_default:
            default_name = row.profile_name
    if default_name is None and profiles:
        default_name = next(iter(profiles))
    return profiles, default_name


def overrides() -> tuple[dict[str, ModelProfileConfig], str | None] | None:
    """返回数据库模型目录；未启用、为空或读取失败时返回 None 回退环境变量。"""

    global _snapshot, _loaded_at
    if not _active:
        return None
    now = monotonic()
    with _lock:
        if _snapshot is not None and now - _loaded_at < CACHE_TTL_SECONDS:
            return _snapshot if _snapshot[0] else None
        try:
            snapshot = _load_from_database()
        except Exception:
            LOGGER.warning("读取数据库模型目录失败，沿用环境变量模型配置", exc_info=True)
            snapshot = ({}, None)
        _snapshot = snapshot
        _loaded_at = now
        return snapshot if snapshot[0] else None