"""Redis 故障策略及真实服务集成；真实集成通过 TEST_REDIS_URL 显式启用。"""

import os
import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine, event, update, insert
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Session

from app.core import cache, config, rate_limit, redis_client
from app.core.config import Settings
from app.core.errors import BusinessValidationError
from app.core.auth import get_current_user
from app.modules.ai import agent_tools, controller, conversation_store, history_access
from app.modules.ai.model import AIConversation, AIMessage
from app.modules.ai.schema import ProductSearchInput
from app.modules.chemicals.model import Chemical
from app.modules.products.controller import get_product
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit


class UnavailableRedis:
    def get(self, *_):
        raise ConnectionError("offline")

    def eval(self, *_):
        raise ConnectionError("offline")


@pytest.fixture
def redis_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def sqlite_transaction_control(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def sqlite_begin(connection):
        connection.exec_driver_sql("BEGIN")
    # 使用真实 ORM 模型的列，替换 MySQL 的时间默认值，不复制业务查询实现。
    with engine.begin() as connection:
        for model in (Chemical, Unit, Product, AIConversation, AIMessage):
            columns = []
            for column in model.__table__.columns:
                declaration = f'"{column.name}" {column.type.compile(dialect=sqlite.dialect())}'
                if column.primary_key:
                    declaration += " PRIMARY KEY"
                if column.name in {"created_at", "updated_at"}:
                    declaration += " DEFAULT CURRENT_TIMESTAMP"
                columns.append(declaration)
            connection.exec_driver_sql(f'CREATE TABLE {model.__tablename__} ({", ".join(columns)})')
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([
            Chemical(id=1, chemical_name="乙醇", cas_no="64-17-5", status="ACTIVE"),
            Unit(id=1, unit_code="KG", unit_name="千克", dimension="MASS", status="ACTIVE"),
            Product(id=1, product_code="P-ETH", product_name="乙醇", chemical_id=1, unit_id=1,
                    status="ACTIVE", version_no=1),
            AIConversation(id=1, user_id=7, title="会话", permission_snapshot={}, status="ACTIVE"),
            AIMessage(id=1, conversation_id=1, message_role="ASSISTANT", content="已保存的答案",
                      citations=[{"type": "text2sql"}]),
        ])
        db.commit()
        yield db
    engine.dispose()


def test_cache_falls_back_when_redis_is_unavailable(redis_db, monkeypatch):
    monkeypatch.setattr(cache, "get_redis", lambda: UnavailableRedis())
    assert cache.cached(redis_db, "product_catalog", "key", TypeAdapter(dict),
                        lambda: {"source": "database"}, ttl=60) == {"source": "database"}


def test_enabled_limiter_fails_closed(monkeypatch):
    monkeypatch.setattr(rate_limit, "get_settings", lambda: Settings(_env_file=None, redis_enabled=True,
                                                                    redis_rate_limit_enabled=True))
    monkeypatch.setattr(rate_limit, "get_redis", lambda: UnavailableRedis())
    with pytest.raises(HTTPException) as caught:
        rate_limit.check_limit(7, "ai")
    assert caught.value.status_code == 503 and caught.value.headers["Retry-After"] == "1"


def test_limiter_configuration_cannot_silently_disable_protection():
    with pytest.raises(ValueError, match="REDIS_ENABLED"):
        Settings(_env_file=None, redis_enabled=False, redis_rate_limit_enabled=True)


@pytest.fixture
def live_redis(monkeypatch):
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("设置 TEST_REDIS_URL 后运行真实 Redis 集成测试")
    prefix = "chemicalops-test-" + uuid4().hex
    settings = Settings(_env_file=None, redis_url=url, redis_enabled=True, redis_rate_limit_enabled=True,
                        redis_key_prefix=prefix, redis_timeout_seconds=2,
                        ai_rate_limit_requests=17, document_rate_limit_requests=3)
    client = Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    client.ping()  # 显式启用时，连接失败应使测试失败，不能跳过。
    for module in (cache, rate_limit, redis_client, conversation_store, config):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(cache, "get_redis", lambda: client)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: client)
    yield client, settings
    keys = list(client.scan_iter(match=prefix + ":*"))
    if keys:
        client.delete(*keys)
    client.close()


def test_concurrent_limiter_is_exact_and_isolates_users_and_categories(live_redis):
    client, settings = live_redis

    def attempt(user_id):
        try:
            rate_limit.check_limit(user_id, "ai")
            return user_id, True
        except HTTPException as exc:
            assert exc.status_code == 429 and int(exc.headers["Retry-After"]) >= 1
            return user_id, False

    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(attempt, [7, 8] * 100))
    for user_id in (7, 8):
        assert sum(allowed for user, allowed in results if user == user_id) == 17
        assert client.pttl(redis_client.redis_key("limit", "ai", user_id)) > 0
    for _ in range(3):
        rate_limit.check_limit(7, "document")
    with pytest.raises(HTTPException) as caught:
        rate_limit.check_limit(7, "document")
    assert caught.value.status_code == 429
    client.pexpire(redis_client.redis_key("limit", "ai", 7), 1)
    time.sleep(0.02)
    rate_limit.check_limit(7, "ai")


def test_product_and_cas_cache_hit_then_invalidate_after_commit(redis_db, live_redis):
    db = redis_db
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda *args: statements.append(args[2]))
    arguments = ProductSearchInput(keyword="64-17-5")
    actor = SimpleNamespace(id=7)
    assert agent_tools.search_products(db, actor, arguments).rows[0].product_name == "乙醇"
    first_count = len(statements)
    assert agent_tools.search_products(db, actor, arguments).rows[0].product_id == 1
    assert len(statements) == first_count
    assert get_product(1, db, actor).product_name == "乙醇"
    first_count = len(statements)
    assert get_product(1, db, actor).product_name == "乙醇"
    assert len(statements) == first_count
    product = db.get(Product, 1)
    product.product_name = "乙醇新名称"
    product.updated_at = datetime.now()
    db.commit()
    assert get_product(1, db, actor).product_name == "乙醇新名称"
    assert agent_tools.search_products(db, actor, arguments).rows[0].product_name == "乙醇新名称"
    db.execute(update(Chemical).where(Chemical.id == 1).values(status="INACTIVE", updated_at=datetime.now()))
    db.commit()
    assert agent_tools.search_products(db, actor, arguments).total_rows == 0


def test_rollback_and_savepoint_preserve_cache_transaction_boundary(redis_db, live_redis):
    db = redis_db
    client, _ = live_redis
    key = redis_client.redis_key("cache-version", "product_catalog")
    original = client.get(key)
    get_product(1, db, SimpleNamespace(id=7))
    with db.begin_nested():
        db.get(Product, 1).product_name = "未提交名称"
        db.get(Product, 1).updated_at = datetime.now()
        db.flush()
    assert client.get(key) == original  # savepoint 提交不能使外层事务提前失效。
    assert get_product(1, db, SimpleNamespace(id=7)).product_name == "未提交名称"
    db.rollback()
    assert client.get(key) == original
    assert get_product(1, db, SimpleNamespace(id=7)).product_name == "乙醇"
    with db.begin_nested():
        db.get(Product, 1).product_name = "正式提交名称"
        db.get(Product, 1).updated_at = datetime.now()
    db.commit()
    assert client.get(key) != original
    assert get_product(1, db, SimpleNamespace(id=7)).product_name == "正式提交名称"


def test_old_concurrent_fill_is_not_visible_in_new_generation(redis_db, live_redis):
    def old_read():
        cache.invalidate("product_catalog")  # 模拟另一请求提交并使旧版本失效。
        return {"name": "old"}

    cache.cached(redis_db, "product_catalog", "race", TypeAdapter(dict), old_read, ttl=60)
    assert cache.cached(redis_db, "product_catalog", "race", TypeAdapter(dict),
                        lambda: {"name": "new"}, ttl=60) == {"name": "new"}


def test_corrupt_cache_recovers_from_database(redis_db, live_redis):
    client, _ = live_redis
    get_product(1, redis_db, SimpleNamespace(id=7))
    keys = list(client.scan_iter(match=redis_client.redis_key("cache", "product_catalog") + ":*"))
    assert len(keys) == 1
    client.set(keys[0], '{"bad": true}', ex=60)
    assert get_product(1, redis_db, SimpleNamespace(id=7)).product_name == "乙醇"


def test_session_cache_recovers_and_rechecks_ownership_and_evidence(redis_db, live_redis, monkeypatch):
    client, _ = live_redis
    actor = SimpleNamespace(id=7)
    first, total = conversation_store.list_messages(redis_db, actor, 1)
    assert total == 1 and first[0].content == "已保存的答案"
    with pytest.raises(BusinessValidationError):
        conversation_store.list_messages(redis_db, SimpleNamespace(id=8), 1)
    monkeypatch.setattr(history_access, "query_accessible", lambda *_: False)
    assert controller.messages(1, 100, redis_db, actor).items[0].content != "已保存的答案"
    keys = list(client.scan_iter(match=redis_client.redis_key("cache", "ai_history") + ":*"))
    assert keys
    for key in keys:
        client.pexpire(key, 1)
    time.sleep(0.02)
    restored, _ = conversation_store.list_messages(redis_db, actor, 1)
    assert restored[0].content == first[0].content
    # Agent 的批量更新语句也必须在提交后使历史快照失效。
    redis_db.execute(update(AIMessage).where(AIMessage.id == 1).values(content="任务已取消。"))
    redis_db.commit()
    assert conversation_store.list_messages(redis_db, actor, 1)[0][0].content == "任务已取消。"

    monkeypatch.setattr(cache, "get_redis", lambda: UnavailableRedis())
    assert conversation_store.list_messages(redis_db, actor, 1)[0][0].content == "任务已取消。"


def test_stream_is_rejected_before_opening_and_cancel_is_not_limited(live_redis, monkeypatch):
    from app.main import handle_http_exception
    from starlette.exceptions import HTTPException as StarletteHTTPException

    api = FastAPI(exception_handlers={StarletteHTTPException: handle_http_exception})
    api.include_router(controller.router)
    actor = SimpleNamespace(id=7)
    api.dependency_overrides[get_current_user] = lambda: actor
    api.dependency_overrides[controller.router.dependencies[0].dependency] = lambda: actor
    for _ in range(17):
        rate_limit.check_limit(7, "ai")
    response = TestClient(api).post("/ai/chat/stream", json={"messages": [{"role": "user", "content": "查询库存"}]})
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["code"] == 429
    from starlette.requests import Request
    rate_limit.limit_ai(Request({"type": "http", "method": "POST", "path": "/ai/agent/tasks/123/cancel", "headers": []}), actor)
    rate_limit.limit_ai(Request({"type": "http", "method": "GET", "path": "/ai/agent/tasks/123", "headers": []}), actor)


def test_cache_latency_and_hit_ratio_sample(redis_db, live_redis, monkeypatch):
    """固定样本报告真实 Redis + SQLite 的端到端查询耗时，不断言必然提速。"""
    client, _ = live_redis
    redis_db.execute(insert(Product), [
        {"id": i, "product_code": f"P-{i}", "product_name": "乙醇规格", "chemical_id": 1,
         "unit_id": 1, "version_no": 1, "status": "ACTIVE"} for i in range(2, 5002)
    ])
    redis_db.commit()
    queries = []
    event.listen(redis_db.get_bind(), "before_cursor_execute",
                 lambda conn, cursor, statement, *_: queries.append(statement) if statement.lstrip().upper().startswith("SELECT") else None)
    actor, arguments = SimpleNamespace(id=7), ProductSearchInput(keyword="64-17-5")
    sample = {}
    for mode in ("without_cache", "cache_aside"):
        monkeypatch.setattr(cache, "get_redis", lambda: None if mode == "without_cache" else client)
        queries.clear()
        durations = []
        for _ in range(100):
            started = time.perf_counter()
            result = agent_tools.search_products(redis_db, actor, arguments)
            durations.append((time.perf_counter() - started) * 1000)
            assert result.total_rows == 5001
        sample[mode] = {"requests": 100, "sql_select_count": len(queries),
                        "mean_ms": round(statistics.mean(durations), 4),
                        "p95_ms": round(sorted(durations)[94], 4)}
    assert sample["without_cache"]["sql_select_count"] == 300
    assert sample["cache_aside"]["sql_select_count"] == 3
    report = {"environment": {"python": platform.python_version(), "database": "SQLite in-memory",
                               "redis_version": client.info("server")["redis_version"], "transport": "localhost Docker"},
              "sample": {"products": 5001, "query": "CAS exact match", "threads": 1,
                         "cache_hits": 99, "cache_misses": 1, "hit_ratio": 0.99}, "latency": sample}
    if path := os.environ.get("REDIS_VALIDATION_REPORT"):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
