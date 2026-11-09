"""Agent 任务反馈的版本快照、覆盖与聚合回归。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.ai import feedback
from app.modules.ai.model import AIAgentTask, AIFeedback
from app.modules.ai.schema import AIFeedbackCreate


@pytest.fixture
def feedback_db(monkeypatch):
    # 生产模型使用 MySQL CURRENT_TIMESTAMP(3)；SQLite 不支持该表达式。
    monkeypatch.setattr(AIFeedback.__table__.c.updated_at, "onupdate", None)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ai_agent_tasks (
                id VARCHAR(32) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status VARCHAR(24) NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                payload JSON NOT NULL,
                reply TEXT NOT NULL,
                error_code VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ai_feedback (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                task_id VARCHAR(32) NOT NULL,
                rating VARCHAR(8) NOT NULL,
                reason_code VARCHAR(32),
                comment VARCHAR(1000),
                correction TEXT,
                prompt_version VARCHAR(100),
                prompt_versions JSON,
                model_name VARCHAR(100),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                UNIQUE (user_id, task_id)
            )
        """))
    session = Session(engine, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _task(session, task_id, *, user_id=1, prompt_version="planner@1-deadbeef"):
    now = datetime.now()
    session.add(AIAgentTask(
        id=task_id, user_id=user_id, status="FAILED", revision=0,
        payload={"run_meta": {
            "prompt_versions": {"routing": "routing@1-cafe", "planner": prompt_version},
            "model": {"provider": "deepseek", "name": "deepseek-chat"},
        }},
        reply="", error_code="TOOL_ERRORS", created_at=now, updated_at=now))
    session.commit()


def test_submit_feedback_snapshots_run_meta_and_upserts(feedback_db):
    _task(feedback_db, "a" * 32)
    user = SimpleNamespace(id=1)

    first = feedback.submit_feedback(feedback_db, user, AIFeedbackCreate(
        task_id="a" * 32, rating="DOWN", reason_code="TOOL_ERROR", comment="选错工具",
        correction="应该查订单列表"))
    assert first.rating == "DOWN"
    assert first.prompt_version == "planner@1-deadbeef"
    assert first.prompt_versions["routing"] == "routing@1-cafe"
    assert first.model_name == "deepseek-chat"

    second = feedback.submit_feedback(feedback_db, user, AIFeedbackCreate(
        task_id="a" * 32, rating="UP"))
    assert second.rating == "UP"
    assert second.reason_code is None
    assert feedback_db.query(AIFeedback).count() == 1


def test_feedback_is_owner_only_and_summary_groups_versions(feedback_db):
    _task(feedback_db, "b" * 32, prompt_version="planner@1-one")
    _task(feedback_db, "c" * 32, prompt_version="planner@1-two")
    user = SimpleNamespace(id=1)
    feedback.submit_feedback(feedback_db, user, AIFeedbackCreate(
        task_id="b" * 32, rating="DOWN", reason_code="FACT_ERROR"))
    feedback.submit_feedback(feedback_db, user, AIFeedbackCreate(
        task_id="c" * 32, rating="UP"))

    summary = feedback.summary(feedback_db, user, days=7)
    assert summary.total == 2 and summary.up == 1 and summary.down == 1
    assert summary.by_reason["FACT_ERROR"] == 1
    assert summary.by_prompt_version["planner@1-one"] == 1
    assert summary.by_prompt_version["planner@1-two"] == 1

    with pytest.raises(ResourceNotFoundError):
        feedback.get_feedback(feedback_db, SimpleNamespace(id=2), "b" * 32)
    with pytest.raises(ResourceNotFoundError):
        feedback.submit_feedback(feedback_db, SimpleNamespace(id=2), AIFeedbackCreate(
            task_id="b" * 32, rating="UP"))


def test_down_feedback_requires_reason(feedback_db):
    _task(feedback_db, "d" * 32)
    with pytest.raises(BusinessValidationError, match="原因"):
        feedback.submit_feedback(feedback_db, SimpleNamespace(id=1), AIFeedbackCreate(
            task_id="d" * 32, rating="DOWN"))


def test_admin_summary_aggregates_users_without_identity_or_text(feedback_db):
    _task(feedback_db, "e" * 32, user_id=1)
    _task(feedback_db, "f" * 32, user_id=2)
    feedback.submit_feedback(feedback_db, SimpleNamespace(id=1), AIFeedbackCreate(
        task_id="e" * 32, rating="DOWN", reason_code="FACT_ERROR", comment="不应出现在聚合中"))
    feedback.submit_feedback(feedback_db, SimpleNamespace(id=2), AIFeedbackCreate(
        task_id="f" * 32, rating="UP"))

    summary = feedback.summary_all(feedback_db, days=7)

    assert summary.total == 2 and summary.users == 2
    assert summary.up == 1 and summary.down == 1
    assert summary.by_reason["FACT_ERROR"] == 1
    assert summary.by_model["deepseek-chat"] == 2
    dumped = summary.model_dump()
    assert "comment" not in dumped and "correction" not in dumped and "user_id" not in dumped