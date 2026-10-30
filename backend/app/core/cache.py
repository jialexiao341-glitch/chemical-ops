"""JSON Cache Aside 与提交后失效；Redis 故障回源，事务中的修改不写缓存。"""

import hashlib
import logging
from time import perf_counter
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import metrics
from app.core.redis_client import get_redis, redis_key


LOGGER = logging.getLogger("chemicalops.cache")
_PENDING = "redis_cache_invalidations"
_TABLE_SPACES = {
    "md_products": "product_catalog", "md_chemicals": "product_catalog", "md_units": "product_catalog",
    "products": "product_catalog", "chemicals": "product_catalog", "units": "product_catalog",
    "md_suppliers": "supplier_directory", "suppliers": "supplier_directory",
    "ai_messages": "ai_history", "ai_conversations": "ai_history",
}


def cached(db: Session, space: str, identity: object, adapter: TypeAdapter, load, *, ttl: int | None = None):
    """只缓存已校验 JSON 快照；版本键防止并发回填旧结果污染新版本。"""
    client = get_redis()
    if client is None or db.new or db.dirty or db.deleted or db.in_nested_transaction() or db.info.get(_PENDING):
        return load()
    ttl = ttl if ttl is not None else get_settings().redis_cache_ttl_seconds
    started = perf_counter()
    version_key = redis_key("cache-version", space)
    digest = hashlib.sha256(str(identity).encode()).hexdigest()
    try:
        version = client.get(version_key) or "0"
        key = redis_key("cache", space, version, digest)
        raw = client.get(key)
        if raw is not None:
            try:
                value = adapter.validate_json(raw)
            except (ValidationError, ValueError):
                client.delete(key)
                metrics.increment("redis_cache", labels={"space": space, "result": "invalid"})
            else:
                metrics.increment("redis_cache", labels={"space": space, "result": "hit"})
                metrics.observe("cached_read_seconds", perf_counter() - started, labels={"space": space, "result": "hit"})
                return value
    except RedisError:
        metrics.increment("redis_cache", labels={"space": space, "result": "unavailable"})
        return load()
    metrics.increment("redis_cache", labels={"space": space, "result": "miss"})
    value = load()
    payload = adapter.dump_json(value)
    # 避免一轮含大量附件或工具轨迹的会话挤占 Redis 内存。
    if len(payload) <= 1024 * 1024:
        try:
            client.set(key, payload, ex=ttl)
        except RedisError:
            metrics.increment("redis_cache", labels={"space": space, "result": "write_error"})
    metrics.observe("cached_read_seconds", perf_counter() - started, labels={"space": space, "result": "miss"})
    return value


def invalidate(space: str) -> None:
    client = get_redis()
    if client is None:
        return
    settings = get_settings()
    try:
        client.set(redis_key("cache-version", space), uuid4().hex,
                   ex=2 * max(settings.redis_cache_ttl_seconds, settings.redis_session_ttl_seconds) + 60)
    except RedisError:
        metrics.increment("redis_cache", labels={"space": space, "result": "invalidation_error"})
        LOGGER.warning("Redis 缓存失效失败 space=%s；旧快照将在 TTL 后过期", space)


def _mark(db: Session, table: str) -> None:
    if (space := _TABLE_SPACES.get(table)) is not None and get_settings().redis_enabled:
        transaction = db.get_nested_transaction() or db.get_transaction()
        db.info.setdefault(_PENDING, {}).setdefault(transaction, set()).add(space)


@event.listens_for(Session, "before_flush")
def _track_changes(db, *_):
    if not get_settings().redis_enabled:
        return
    for obj in db.new | db.dirty | db.deleted:
        _mark(db, obj.__table__.name)


@event.listens_for(Session, "do_orm_execute")
def _track_bulk_changes(state):
    if not get_settings().redis_enabled:
        return
    if state.is_update or state.is_delete or state.is_insert:
        table = getattr(state.statement, "table", None)
        if table is not None:
            # 执行前可能尚未建立事务，先由 Session 创建当前事务。
            if not state.session.in_transaction():
                state.session.begin()
            _mark(state.session, table.name)


@event.listens_for(Session, "after_commit")
def _commit_invalidations(db):
    pending = db.info.get(_PENDING, {})
    transaction = db.get_nested_transaction() or db.get_transaction()
    spaces = pending.pop(transaction, set())
    if transaction is not None and transaction.nested:
        pending.setdefault(transaction.parent, set()).update(spaces)
    else:
        for space in spaces:
            invalidate(space)
    if not pending:
        db.info.pop(_PENDING, None)


@event.listens_for(Session, "after_soft_rollback")
def _rollback_invalidations(db, transaction):
    pending = db.info.get(_PENDING, {})
    pending.pop(transaction, None)
    if not transaction.nested:
        pending.clear()
    if not pending:
        db.info.pop(_PENDING, None)


@event.listens_for(Session, "after_transaction_end")
def _clear_closed_transaction(db, transaction):
    if transaction.parent is None:
        db.info.pop(_PENDING, None)
