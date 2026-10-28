"""接口测试公共夹具。"""

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


# 普通回归测试不共享本地应用的缓存和用户配额；真实 Redis 用例自行启用隔离前缀。
os.environ["OTEL_ENABLED"] = "false"
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("REDIS_RATE_LIMIT_ENABLED", "false")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import engine, get_db  # noqa: E402


def grant_test_warehouse(db: Session, user_id: int, warehouse_id: int) -> None:
    """在测试事务中为样本账号显式授权仓库。"""
    from app.modules.system.model import UserWarehouseScope, UserWarehouseGrant
    if db.get(UserWarehouseScope, user_id) is None:
        db.add(UserWarehouseScope(user_id=user_id))
        db.flush()
    if db.get(UserWarehouseGrant, (user_id, warehouse_id)) is None:
        db.add(UserWarehouseGrant(user_id=user_id, warehouse_id=warehouse_id))
        db.flush()
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.system.model import User  # noqa: E402
from sqlalchemy import select  # noqa: E402


class TestSession(Session):
    """测试会话把业务 commit 转换为 flush，最终由夹具统一回滚。"""

    def commit(self) -> None:
        """不提交外部测试事务，只刷新当前会话。"""

        self.flush()


class _SecretString(str):
    """Keep test credentials out of pytest's fixture representations."""

    def __repr__(self) -> str:
        return "<redacted>"


@pytest.fixture(scope="session")
def db_engine():
    """检查测试数据库连接。"""

    try:
        connection = engine.connect()
        connection.close()
    except SQLAlchemyError as exc:
        if os.environ.get("CI", "").strip().lower() == "true":
            pytest.fail(f"CI 测试数据库不可用，拒绝跳过集成测试：{exc}")
        pytest.skip(f"测试数据库不可用：{exc}")
    return engine


@pytest.fixture
def db_session(db_engine) -> Generator[TestSession, None, None]:
    """为每个测试创建独立事务，测试后回滚。"""

    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestSession(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: TestSession) -> Generator[TestClient, None, None]:
    """将 API 请求绑定到当前测试事务。"""

    def override_get_db() -> Generator[TestSession, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def demo_password():
    """读取当前开发环境演示账号密码且避免失败报告回显。"""

    from app.core.config import get_settings

    password = get_settings().demo_default_password
    if not password:
        pytest.skip("测试环境未配置演示账号密码")
    return _SecretString(password)


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    """在当前回滚事务内临时设置测试口令，再登录并返回 Bearer 请求头。"""

    # 不假设本机演示账号散列与测试配置相同，也不持久化任何测试口令。
    override = app.dependency_overrides.get(get_db)
    if override is not None:
        session_generator = override()
        db = next(session_generator)
        user = db.scalar(select(User).where(User.username == username))
        if user is not None:
            user.password_hash = hash_password(password)
            db.flush()
        session_generator.close()

    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
