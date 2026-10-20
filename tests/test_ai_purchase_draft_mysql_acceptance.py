"""MySQL acceptance checks for the purchase-draft confirmation boundary.

This module creates a uniquely named temporary database and drops it afterwards.
It never uses the configured application database.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.modules.ai import purchase_draft_confirmations as confirmations
from app.modules.ai.model import AIPurchaseDraftConfirmation
from app.modules.ai.schema import AIPurchaseDraftConfirm
from app.modules.purchase_requests.model import (
    PurchaseRequest,
    PurchaseRequestApproval,
    PurchaseRequestItem,
)
from app.modules.system.audit import AuditLog


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_mysql_engine():
    config = dotenv_values(ROOT / ".env")
    password = config.get("MYSQL_ROOT_PASSWORD")
    if not password:
        pytest.skip("Isolated MySQL acceptance credentials unavailable")

    host = config.get("MYSQL_HOST", "127.0.0.1")
    port = int(config.get("MYSQL_PORT", "3306"))
    database = f"chemicalops_agent_confirm_{uuid4().hex[:12]}"
    admin = create_engine(URL.create(
        "mysql+pymysql", username="root", password=password, host=host, port=port,
    ), pool_pre_ping=True, connect_args={"connect_timeout": 2})
    engine = None
    database_created = False
    try:
        try:
            with admin.connect():
                pass
        except OperationalError as exc:
            # A missing local server is an unavailable integration dependency;
            # authentication/configuration failures remain visible to the test.
            if getattr(exc.orig, "args", (None,))[0] == 2003:
                pytest.skip("Isolated MySQL server is unavailable")
            raise

        with admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4")
        database_created = True

        engine = create_engine(URL.create(
            "mysql+pymysql", username="root", password=password, host=host,
            port=port, database=database,
        ), pool_pre_ping=True)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE sys_users (id INT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
            )
            connection.exec_driver_sql(
                "CREATE TABLE purchase_requests ("
                "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB"
            )
        AIPurchaseDraftConfirmation.__table__.create(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f"DROP DATABASE IF EXISTS `{database}`")
        admin.dispose()


@pytest.fixture
def isolated_mysql_purchase_service_engine(isolated_mysql_engine):
    """An isolated schema with real purchase-request, item, and audit tables."""
    engine = isolated_mysql_engine
    # Replace the minimal parent table from the focused idempotency fixture.
    AIPurchaseDraftConfirmation.__table__.drop(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE purchase_requests")
    with engine.begin() as connection:
        # Keep support tables minimal while retaining the columns read by the
        # real purchase-request service. The business tables below use their
        # production SQLAlchemy models and constraints.
        connection.exec_driver_sql(
            "CREATE TABLE sys_departments ("
            "id INT NOT NULL PRIMARY KEY, parent_id INT NULL, "
            "department_code VARCHAR(64) NOT NULL, department_name VARCHAR(128) NOT NULL, "
            "manager_id INT NULL, status VARCHAR(20) NOT NULL, "
            "created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), "
            "updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) "
            "ON UPDATE CURRENT_TIMESTAMP(3)) ENGINE=InnoDB"
        )
        connection.exec_driver_sql(
            "CREATE TABLE sys_roles ("
            "id INT NOT NULL PRIMARY KEY, role_code VARCHAR(64) NOT NULL, "
            "status VARCHAR(20) NOT NULL) ENGINE=InnoDB"
        )
        connection.exec_driver_sql(
            "CREATE TABLE sys_user_roles ("
            "user_id INT NOT NULL, role_id INT NOT NULL, "
            "PRIMARY KEY (user_id, role_id)) ENGINE=InnoDB"
        )
        connection.exec_driver_sql(
            "CREATE TABLE md_units ("
            "id INT NOT NULL PRIMARY KEY, unit_code VARCHAR(32) NOT NULL, "
            "unit_name VARCHAR(64) NOT NULL, dimension VARCHAR(32) NOT NULL, "
            "status VARCHAR(20) NOT NULL) ENGINE=InnoDB"
        )
        connection.exec_driver_sql(
            "CREATE TABLE md_products (id INT NOT NULL PRIMARY KEY) ENGINE=InnoDB"
        )
    PurchaseRequest.__table__.create(engine)
    PurchaseRequestItem.__table__.create(engine)
    PurchaseRequestApproval.__table__.create(engine)
    AuditLog.__table__.create(engine)
    AIPurchaseDraftConfirmation.__table__.create(engine)
    return engine


def _seed_pending_confirmation(engine, payload: dict, confirmation_id: str) -> None:
    with Session(engine) as setup:
        setup.execute(text("INSERT INTO sys_users (id) VALUES (5)"))
        setup.execute(text(
            "INSERT INTO sys_departments "
            "(id, department_code, department_name, status) "
            "VALUES (2, 'ACCEPTANCE', 'Acceptance', 'ACTIVE')"
        ))
        setup.execute(text(
            "INSERT INTO md_units (id, unit_code, unit_name, dimension, status) "
            "VALUES (3, 'KG', '千克', 'MASS', 'ACTIVE')"
        ))
        setup.add(AIPurchaseDraftConfirmation(
            confirmation_id=confirmation_id,
            user_id=5,
            preview_version=1,
            request_hash=confirmations._hash(payload),
            draft_payload=payload,
            object_versions={"actor_department_id": 2, "products": {}, "units": {}},
            evidence=[],
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        setup.commit()


def _real_service_payload(purpose: str) -> dict:
    return {
        "purpose": purpose,
        "priority": "NORMAL",
        "currency_code": "CNY",
        "items": [{
            "requested_name": "ethanol",
            "product_id": None,
            "quantity": "2",
            "unit_id": 3,
        }],
    }


def _grant_confirmation_permission(monkeypatch) -> None:
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(
        confirmations, "get_user_permission_codes",
        lambda *_args: ["procurement.requests.write"],
    )


def test_confirmation_commits_real_request_items_audit_and_confirmation_together(
    isolated_mysql_purchase_service_engine, monkeypatch,
):
    """The confirmation transaction includes all writes from the real domain service."""
    engine = isolated_mysql_purchase_service_engine
    _grant_confirmation_permission(monkeypatch)
    payload = _real_service_payload("Real purchase service acceptance")
    confirmation_id = uuid4().hex
    _seed_pending_confirmation(engine, payload, confirmation_id)
    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    request = AIPurchaseDraftConfirm(
        confirmation_id=confirmation_id, preview_version=1, confirm=True,
    )

    with Session(engine, expire_on_commit=False) as db:
        result = confirmations.confirm_purchase_draft(db, user, request)

    assert result["status"] == "DRAFT"
    assert result["purpose"] == payload["purpose"]
    assert len(result["items"]) == 1
    request_id = result["id"]
    with engine.connect() as connection:
        saved_confirmation = connection.execute(text(
            "SELECT status, purchase_request_id FROM ai_purchase_draft_confirmations "
            "WHERE confirmation_id = :id"
        ), {"id": confirmation_id}).one()
        assert saved_confirmation == ("EXECUTED", request_id)
        assert connection.scalar(text(
            "SELECT COUNT(*) FROM purchase_requests WHERE id = :id AND status = 'DRAFT'"
        ), {"id": request_id}) == 1
        item = connection.execute(text(
            "SELECT request_id, line_no, requested_name, quantity, unit_id "
            "FROM purchase_request_items WHERE request_id = :id"
        ), {"id": request_id}).one()
        assert item == (request_id, 1, "ethanol", 2, 3)
        audit = connection.execute(text(
            "SELECT actor_id, action_type, resource_type, resource_id, result_status "
            "FROM sys_audit_logs WHERE resource_id = :id"
        ), {"id": request_id}).one()
        assert audit == (5, "CREATE", "PURCHASE_REQUEST", request_id, "SUCCESS")


def test_real_purchase_service_writes_roll_back_if_commit_fails_after_flush(
    isolated_mysql_purchase_service_engine, monkeypatch,
):
    """A commit failure after all writes flush rolls every table back."""
    engine = isolated_mysql_purchase_service_engine
    _grant_confirmation_permission(monkeypatch)
    payload = _real_service_payload("Real purchase service rollback acceptance")
    confirmation_id = uuid4().hex
    _seed_pending_confirmation(engine, payload, confirmation_id)

    class _FailAfterFlushSession(Session):
        def commit(self):
            self.flush()
            assert self.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 1
            assert self.scalar(text("SELECT COUNT(*) FROM purchase_request_items")) == 1
            assert self.scalar(text("SELECT COUNT(*) FROM sys_audit_logs")) == 1
            assert self.scalar(text(
                "SELECT COUNT(*) FROM ai_purchase_draft_confirmations "
                "WHERE confirmation_id = :id AND status = 'EXECUTED'"
            ), {"id": confirmation_id}) == 1
            raise RuntimeError("simulated commit failure after flush")

    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    request = AIPurchaseDraftConfirm(
        confirmation_id=confirmation_id, preview_version=1, confirm=True,
    )
    with _FailAfterFlushSession(engine, expire_on_commit=False) as db:
        with pytest.raises(RuntimeError, match="simulated commit failure after flush"):
            confirmations.confirm_purchase_draft(db, user, request)

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_request_items")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM sys_audit_logs")) == 0
        assert connection.scalar(text(
            "SELECT status FROM ai_purchase_draft_confirmations WHERE confirmation_id = :id"
        ), {"id": confirmation_id}) == "PENDING"


def test_concurrent_confirmation_creates_one_draft(isolated_mysql_engine, monkeypatch):
    """A concurrent replay waits for the locked snapshot and returns its result."""
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(
        confirmations, "get_user_permission_codes",
        lambda *_args: ["procurement.requests.write"],
    )

    payload = {
        "purpose": "Acceptance test",
        "priority": "NORMAL",
        "currency_code": "CNY",
        "items": [{"requested_name": "ethanol", "product_id": None, "quantity": "2", "unit_id": 3}],
    }
    confirmation_id = uuid4().hex
    with Session(isolated_mysql_engine) as setup:
        setup.execute(text("INSERT INTO sys_users (id) VALUES (5)"))
        setup.add(AIPurchaseDraftConfirmation(
            confirmation_id=confirmation_id,
            user_id=5,
            preview_version=1,
            request_hash=confirmations._hash(payload),
            draft_payload=payload,
            object_versions={"actor_department_id": 2, "products": {}, "units": {}},
            evidence=[],
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        setup.commit()

    class _Read:
        @classmethod
        def model_validate(cls, _request):
            return cls()

        def model_dump(self, **_kwargs):
            return {"request_no": "PR-ACCEPTANCE", "status": "DRAFT"}

    monkeypatch.setattr(confirmations, "PurchaseRequestRead", _Read)
    entered_domain_service = Event()
    release_domain_service = Event()

    def create_request(db, _user, _draft, *, commit):
        assert commit is False
        entered_domain_service.set()
        if not release_domain_service.wait(timeout=10):
            raise TimeoutError("test did not release the first confirmation")
        result = db.execute(text("INSERT INTO purchase_requests () VALUES ()"))
        return SimpleNamespace(id=result.lastrowid)

    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", create_request)
    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    request = AIPurchaseDraftConfirm(
        confirmation_id=confirmation_id, preview_version=1, confirm=True,
    )

    def confirm_once():
        with Session(isolated_mysql_engine, expire_on_commit=False) as db:
            return confirmations.confirm_purchase_draft(db, user, request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(confirm_once)
        assert entered_domain_service.wait(timeout=10)
        second = pool.submit(confirm_once)
        sleep(0.2)  # Allow the second transaction to contend on SELECT ... FOR UPDATE.
        release_domain_service.set()
        first_result = first.result(timeout=10)
        second_result = second.result(timeout=10)

    assert first_result == second_result == {
        "request_no": "PR-ACCEPTANCE", "status": "DRAFT",
    }
    with isolated_mysql_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 1
        assert connection.scalar(text(
            "SELECT status FROM ai_purchase_draft_confirmations WHERE confirmation_id = :id"
        ), {"id": confirmation_id}) == "EXECUTED"


def test_domain_failure_rolls_back_draft_and_allows_confirmation_retry(
    isolated_mysql_engine, monkeypatch,
):
    """A failed domain write leaves neither a partial draft nor a consumed snapshot."""
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(
        confirmations, "get_user_permission_codes",
        lambda *_args: ["procurement.requests.write"],
    )

    payload = {
        "purpose": "Failure recovery acceptance",
        "priority": "NORMAL",
        "currency_code": "CNY",
        "items": [{"requested_name": "ethanol", "product_id": None, "quantity": "2", "unit_id": 3}],
    }
    confirmation_id = uuid4().hex
    with Session(isolated_mysql_engine) as setup:
        setup.execute(text("INSERT INTO sys_users (id) VALUES (5)"))
        setup.add(AIPurchaseDraftConfirmation(
            confirmation_id=confirmation_id,
            user_id=5,
            preview_version=1,
            request_hash=confirmations._hash(payload),
            draft_payload=payload,
            object_versions={"actor_department_id": 2, "products": {}, "units": {}},
            evidence=[],
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        setup.commit()

    def fail_after_insert(db, _user, _draft, *, commit):
        assert commit is False
        db.execute(text("INSERT INTO purchase_requests () VALUES ()"))
        raise RuntimeError("simulated domain-service failure")

    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", fail_after_insert)
    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    request = AIPurchaseDraftConfirm(
        confirmation_id=confirmation_id, preview_version=1, confirm=True,
    )
    with Session(isolated_mysql_engine, expire_on_commit=False) as db:
        with pytest.raises(RuntimeError, match="simulated domain-service failure"):
            confirmations.confirm_purchase_draft(db, user, request)

    with isolated_mysql_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 0
        assert connection.scalar(text(
            "SELECT status FROM ai_purchase_draft_confirmations WHERE confirmation_id = :id"
        ), {"id": confirmation_id}) == "PENDING"

    class _Read:
        @classmethod
        def model_validate(cls, _request):
            return cls()

        def model_dump(self, **_kwargs):
            return {"request_no": "PR-RETRY", "status": "DRAFT"}

    monkeypatch.setattr(confirmations, "PurchaseRequestRead", _Read)

    def succeed(db, _user, _draft, *, commit):
        assert commit is False
        result = db.execute(text("INSERT INTO purchase_requests () VALUES ()"))
        return SimpleNamespace(id=result.lastrowid)

    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", succeed)
    with Session(isolated_mysql_engine, expire_on_commit=False) as db:
        result = confirmations.confirm_purchase_draft(db, user, request)

    assert result == {"request_no": "PR-RETRY", "status": "DRAFT"}
    with isolated_mysql_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 1
        assert connection.scalar(text(
            "SELECT status FROM ai_purchase_draft_confirmations WHERE confirmation_id = :id"
        ), {"id": confirmation_id}) == "EXECUTED"


def test_retry_after_committed_response_loss_returns_persisted_result(
    isolated_mysql_engine, monkeypatch,
):
    """A new session can replay a committed confirmation without creating again."""
    monkeypatch.setattr(confirmations, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(
        confirmations, "get_user_permission_codes",
        lambda *_args: ["procurement.requests.write"],
    )

    payload = {
        "purpose": "Response-loss acceptance",
        "priority": "NORMAL",
        "currency_code": "CNY",
        "items": [{"requested_name": "ethanol", "product_id": None, "quantity": "2", "unit_id": 3}],
    }
    confirmation_id = uuid4().hex
    with Session(isolated_mysql_engine) as setup:
        setup.execute(text("INSERT INTO sys_users (id) VALUES (5)"))
        setup.add(AIPurchaseDraftConfirmation(
            confirmation_id=confirmation_id,
            user_id=5,
            preview_version=1,
            request_hash=confirmations._hash(payload),
            draft_payload=payload,
            object_versions={"actor_department_id": 2, "products": {}, "units": {}},
            evidence=[],
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        ))
        setup.commit()

    class _Read:
        @classmethod
        def model_validate(cls, _request):
            return cls()

        def model_dump(self, **_kwargs):
            return {"request_no": "PR-REPLAY", "status": "DRAFT"}

    monkeypatch.setattr(confirmations, "PurchaseRequestRead", _Read)
    writes = []

    def create_request(db, _user, _draft, *, commit):
        assert commit is False
        result = db.execute(text("INSERT INTO purchase_requests () VALUES ()"))
        writes.append(result.lastrowid)
        return SimpleNamespace(id=result.lastrowid)

    monkeypatch.setattr(confirmations.purchase_request_service, "create_request", create_request)
    user = SimpleNamespace(id=5, status="ACTIVE", department_id=2)
    request = AIPurchaseDraftConfirm(
        confirmation_id=confirmation_id, preview_version=1, confirm=True,
    )

    # The first response is intentionally discarded, as if the client disconnected
    # after the database commit but before receiving the HTTP response.
    with Session(isolated_mysql_engine, expire_on_commit=False) as db:
        confirmations.confirm_purchase_draft(db, user, request)
    with Session(isolated_mysql_engine, expire_on_commit=False) as restarted_session:
        replayed = confirmations.confirm_purchase_draft(restarted_session, user, request)

    assert replayed == {"request_no": "PR-REPLAY", "status": "DRAFT"}
    assert len(writes) == 1
    with isolated_mysql_engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM purchase_requests")) == 1
        assert connection.scalar(text(
            "SELECT status FROM ai_purchase_draft_confirmations WHERE confirmation_id = :id"
        ), {"id": confirmation_id}) == "EXECUTED"
