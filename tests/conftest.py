"""接口测试公共夹具。"""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402


class TestSession(Session):
    """测试会话把业务 commit 转换为 flush，最终由夹具统一回滚。"""

    def commit(self) -> None:
        """不提交外部测试事务，只刷新当前会话。"""

        self.flush()


@pytest.fixture(scope="session")
def db_engine():
    """检查测试数据库连接。"""

    try:
        connection = engine.connect()
        connection.close()
    except SQLAlchemyError as exc:
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
    """读取当前开发环境演示账号密码。"""

    from app.core.config import get_settings

    return get_settings().demo_default_password or "ChemicalOps@2026"


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    """登录演示账号并返回 Bearer 请求头。"""

    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
