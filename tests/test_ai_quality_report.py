"""质量证据面：按错误、工具、版本和反馈筛选，不返回问题原文或用户身份。"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.modules.ai import quality_report
from app.modules.ai.model import AIAgentTask, AIFeedback


@pytest.fixture
def quality_db():
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
                updated_at DATETIME NOT NULL
            )
        """))
    session = Session(engine, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _task(session, task_id, *, error_code=None, error_class=None, recovery=None,
          planner="planner@1-aaa", tool=None, model="deepseek-chat", days_ago=1):
    now = datetime.now() - timedelta(days=days_ago)
    trace = [{"action": "call_tool", "tool": tool}] if tool else []
    session.add(AIAgentTask(
        id=task_id, user_id=1, status="FAILED" if error_code else "SUCCEEDED",
        revision=0,
        payload={"run_meta": {
            "prompt_versions": {"routing": "routing@1-bbb", "planner": planner},
            "model": {"provider": "deepseek", "name": model},
            "error": {"code": error_code, "class": error_class, "recovery": recovery},
        }, "trace": trace},
        reply="", error_code=error_code, created_at=now, updated_at=now))


def _feedback(session, feedback_id, task_id, rating, reason=None, days_ago=1):
    now = datetime.now() - timedelta(days=days_ago)
    session.add(AIFeedback(
        id=feedback_id, user_id=1, task_id=task_id, rating=rating,
        reason_code=reason, comment="不要出现在聚合里", correction="也不要出现",
        prompt_version="planner@1-aaa", created_at=now, updated_at=now))


def _seed(session):
    _task(session, "task-a", error_code="TOOL_ERRORS", error_class="BUSINESS_INVALID",
          recovery="FIX_INPUT", planner="planner@1-aaa", tool="purchase_orders.search")
    _task(session, "task-b", planner="planner@1-aaa", tool="purchase_orders.search")
    _task(session, "task-c", error_code="CONTEXT_LIMIT", error_class="BUDGET",
          recovery="NARROW_SCOPE", planner="planner@1-bbb", tool="inventory.query_available")
    _feedback(session, 1, "task-a", "DOWN", "TOOL_ERROR")
    _feedback(session, 2, "task-b", "UP")
    session.commit()


def test_quality_summary_groups_by_error_tool_and_version(quality_db):
    _seed(quality_db)

    report = quality_report.summarize(quality_db, days=7)

    assert report["tasks"] == 3
    assert report["failed_tasks"] == 2
    assert report["feedback"] == 2
    assert report["up"] == 1 and report["down"] == 1
    assert report["down_rate"] == 0.5
    assert {row["key"]: row["count"] for row in report["by_error_code"]} == {"TOOL_ERRORS": 1, "CONTEXT_LIMIT": 1}
    assert {row["key"]: row["count"] for row in report["by_error_class"]} == {"BUDGET": 1, "BUSINESS_INVALID": 1}
    assert {row["key"]: row["count"] for row in report["by_recovery"]} == {"FIX_INPUT": 1, "NARROW_SCOPE": 1}
    assert {row["key"]: row["count"] for row in report["by_tool"]} == {"purchase_orders.search": 2, "inventory.query_available": 1}
    assert report["available_prompt_versions"] == [
        "planner@1-aaa", "planner@1-bbb", "routing@1-bbb"]
    assert report["available_tools"] == ["inventory.query_available", "purchase_orders.search"]
    assert report["available_error_classes"] == ["BUDGET", "BUSINESS_INVALID"]
    assert report["samples"]["TOOL_ERRORS"] == ["task-a"]
    assert "question" not in report and "user_id" not in str(report)
    assert "不要出现在聚合里" not in str(report)


def test_quality_summary_applies_task_and_feedback_filters(quality_db):
    _seed(quality_db)

    by_version = quality_report.summarize(quality_db, days=7, prompt_version="planner@1-bbb")
    assert by_version["tasks"] == 1 and by_version["failed_tasks"] == 1
    assert by_version["feedback"] == 0
    assert by_version["filters"]["prompt_version"] == "planner@1-bbb"

    by_error = quality_report.summarize(quality_db, days=7, error_class="BUSINESS_INVALID")
    assert by_error["tasks"] == 1 and by_error["samples"]["TOOL_ERRORS"] == ["task-a"]

    by_tool = quality_report.summarize(quality_db, days=7, tool="purchase_orders.search")
    assert by_tool["tasks"] == 2 and by_tool["feedback"] == 2

    down_only = quality_report.summarize(quality_db, days=7, rating="DOWN")
    assert down_only["tasks"] == 1 and down_only["failed_tasks"] == 1
    assert down_only["feedback"] == 1 and down_only["down"] == 1


def test_quality_summary_marks_truncated_task_scan(quality_db, monkeypatch):
    _seed(quality_db)
    monkeypatch.setattr(quality_report, "MAX_TASKS", 2)

    report = quality_report.summarize(quality_db, days=7)

    assert report["truncated"] is True
    assert report["tasks"] == 2


def test_quality_summary_ignores_rows_outside_window(quality_db):
    _task(quality_db, "old-task", error_code="TOOL_ERRORS", error_class="BUSINESS_INVALID",
          recovery="FIX_INPUT", days_ago=30)
    _task(quality_db, "new-task", days_ago=1)
    quality_db.commit()

    report = quality_report.summarize(quality_db, days=7)

    assert report["tasks"] == 1
    assert report["failed_tasks"] == 0
    assert "old-task" not in str(report)
