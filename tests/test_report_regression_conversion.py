"""生产转化时长统计：只认已批准且带来源任务的记录，空样本不伪造数字。"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.modules.ai.model import AIAgentTask, AIFeedback, AIRegressionCase
from scripts import report_regression_conversion as report

_DDL = (
    """CREATE TABLE ai_agent_tasks (
        id VARCHAR(32) PRIMARY KEY, user_id INTEGER NOT NULL, status VARCHAR(24) NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0, payload JSON NOT NULL, reply TEXT NOT NULL,
        error_code VARCHAR(64), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE ai_feedback (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, task_id VARCHAR(32) NOT NULL,
        rating VARCHAR(8) NOT NULL, reason_code VARCHAR(32), comment VARCHAR(1000),
        correction TEXT, prompt_version VARCHAR(100), prompt_versions JSON,
        model_name VARCHAR(100), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE ai_regression_cases (
        id INTEGER PRIMARY KEY, case_key VARCHAR(64) NOT NULL UNIQUE,
        source_task_id VARCHAR(32), source_task_hash VARCHAR(64),
        source_prompt_version VARCHAR(100), question TEXT NOT NULL,
        expected_execution_mode VARCHAR(16) NOT NULL, expected_tasks JSON NOT NULL,
        forbidden_tasks JSON NOT NULL, note VARCHAR(500),
        status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', created_by INTEGER NOT NULL,
        reviewed_by INTEGER, reviewed_at DATETIME, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )""",
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _DDL:
            connection.execute(text(statement))
    return Session(engine, autoflush=False, expire_on_commit=False)


def _task(db, task_id, created_at, *, error_code=None, feedback=True):
    db.add(AIAgentTask(
        id=task_id, user_id=1, status="FAILED", revision=0,
        payload={"messages": ["合成问题"]}, reply="", error_code=error_code,
        created_at=created_at, updated_at=created_at))
    if not feedback:
        return
    db.add(AIFeedback(
        id=None, user_id=1, task_id=task_id, rating="DOWN", reason_code="WRONG_ANSWER",
        comment=None, correction=None, prompt_version=None, prompt_versions=None,
        model_name=None, created_at=created_at, updated_at=created_at))


def _case(db, case_key, source_task_id, reviewed_at):
    db.add(AIRegressionCase(
        case_key=case_key, source_task_id=source_task_id, question="合成问题",
        expected_execution_mode="agent", expected_tasks=[], forbidden_tasks=[],
        status="APPROVED", created_by=1, reviewed_by=1, reviewed_at=reviewed_at,
        created_at=reviewed_at, updated_at=reviewed_at))


def test_collects_only_approved_cases_with_source_and_excludes_synthetic():
    db = _db()
    now = datetime.now()
    _task(db, "TASK-FAST", now - timedelta(hours=3))
    _case(db, "PR-FAST", "TASK-FAST", now)
    _task(db, "TASK-SLOW", now - timedelta(hours=40))
    _case(db, "PR-SLOW", "TASK-SLOW", now)
    _task(db, "SYN-TASK-1", now - timedelta(hours=1))
    _case(db, "PR-SYN", "SYN-TASK-1", now)
    _task(db, "TASK-INFRA", now - timedelta(hours=2), error_code="WORKER_UNAVAILABLE",
          feedback=False)
    _case(db, "PR-INFRA", "TASK-INFRA", now)
    db.add(AIRegressionCase(
        case_key="PR-DRAFT", source_task_id="TASK-FAST", question="合成问题",
        expected_execution_mode="agent", expected_tasks=[], forbidden_tasks=[],
        status="DRAFT", created_by=1, created_at=now, updated_at=now))
    db.commit()

    rows, excluded, missing, excluded_infra = report.collect_rows(db, days=90)

    assert excluded == 1 and missing == 0 and excluded_infra == 1
    assert {row["case_key"] for row in rows} == {"PR-FAST", "PR-SLOW"}
    assert all("TASK-" not in row["source_task_hash"] for row in rows)
    assert {row["source"] for row in rows} == {"feedback"}

    summary = report.summarize(rows, window_days=90, excluded_synthetic=excluded,
                              excluded_infra=excluded_infra)
    assert summary["status"] == "OK"
    assert summary["excluded_infra"] == 1
    assert summary["samples"] == 2
    assert summary["hours"]["within_24h"] == 1
    assert summary["hours"]["p50"] is not None
    assert summary["draft_to_approval"]["within_24h"] == 2
    assert summary["pending"]["samples"] == 0


def test_empty_production_sample_reports_no_data_instead_of_zero_duration():
    summary = report.summarize([], window_days=90, excluded_synthetic=2, missing_source=0)

    assert summary["status"] == "NO_PRODUCTION_SAMPLES"
    assert summary["samples"] == 0
    assert summary["hours"]["p50"] is None
    assert summary["hours"]["within_24h_rate"] is None
    assert summary["draft_to_approval"]["p50"] is None
    assert "没有生产" in summary["note"]
    text = report.render_text(summary)
    assert "NO_PRODUCTION_SAMPLES" in text
    assert "不要用 fixture" in text


def test_pending_drafts_are_counted_with_wait_time():
    db = _db()
    now = datetime.now()
    _task(db, "TASK-WAIT", now - timedelta(hours=10))
    db.add(AIRegressionCase(
        case_key="PR-WAIT", source_task_id="TASK-WAIT", question="合成问题",
        expected_execution_mode="agent", expected_tasks=[], forbidden_tasks=[],
        status="DRAFT", created_by=1, created_at=now - timedelta(hours=30),
        updated_at=now))
    db.commit()

    pending = report.collect_pending(db, days=90)
    summary = report.summarize([], window_days=90, excluded_synthetic=0, pending=pending)

    assert len(pending) == 1
    assert pending[0]["wait_hours"] > 24
    assert summary["pending"]["samples"] == 1
    assert summary["pending"]["over_24h"] == 1


def test_all_pass_lower_bound_quantifies_small_sample():
    assert report._metric([2.0] * 9)["over_24h_upper_95"] == 0.283
    assert report._metric([2.0, 30.0])["over_24h_upper_95"] is None
    assert report._metric([])["over_24h_upper_95"] is None


def test_percentile_interpolates_and_task_hash_hides_id():
    assert report.percentile([], 0.5) is None
    assert report.percentile([4.0], 0.5) == 4.0
    assert report.percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert report.percentile([1.0, 2.0], 0.9) == 1.9
    assert len(report.task_hash("TASK-RAW")) == 12
    assert "TASK-RAW" not in report.task_hash("TASK-RAW")