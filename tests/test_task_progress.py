"""任务进展诊断规则：只用确定性信号，不改变任务状态。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core.config import get_settings
from app.modules.task_queue.progress import diagnose


def _execution(*, status="RUNNING", created=0, started=60, heartbeat=5, updated=10,
               checkpoint=None, attempt=1):
    now = datetime(2026, 11, 10, 12, 0, 0)
    return SimpleNamespace(
        id="exec-1",
        task_type="agent.run",
        business_id="task-1",
        status=status,
        attempt_count=attempt,
        created_at=now - timedelta(seconds=created),
        started_at=None if started is None else now - timedelta(seconds=started),
        heartbeat_at=None if heartbeat is None else now - timedelta(seconds=heartbeat),
        updated_at=now - timedelta(seconds=updated),
        checkpoint=checkpoint or {},
    ), now


def test_healthy_running_task_is_ok():
    execution, now = _execution(created=120, checkpoint={"decisions": 4, "failures": 0,
                                                "token_budget": {"used_tokens": 100, "limit": 1000},
                                                "timings": {"llm_seconds": 12.5, "tool_seconds": 3.25}})
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "OK"
    assert result.recommendation == "WAIT"
    assert result.last_progress_seconds == 10
    assert result.llm_seconds == 12.5
    assert result.tool_seconds == 3.25
    assert result.queued_seconds == 60


def test_heartbeat_alive_but_no_progress_is_stalled():
    execution, now = _execution(heartbeat=5, updated=400)
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "STALLED"
    assert result.recommendation == "MANUAL_REVIEW"
    assert any("没有新的检查点更新" in reason for reason in result.reasons)
    assert any("进程仍存活" in reason for reason in result.reasons)


def test_repeated_failures_are_error_loop():
    execution, now = _execution(checkpoint={"decisions": 3, "failures": 2})
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "ERROR_LOOP"
    assert result.recommendation == "MANUAL_REVIEW"


def test_near_budget_is_budget_risk():
    execution, now = _execution(checkpoint={"decisions": 2, "failures": 0,
                                            "token_budget": {"used_tokens": 950, "limit": 1000}})
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "BUDGET_RISK"
    assert result.recommendation == "NOTIFY_USER"


def test_long_running_is_slow_not_stalled():
    execution, now = _execution(started=110, updated=5)
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "SLOW"
    assert result.recommendation == "WAIT"


def test_queued_too_long_is_reported():
    execution, now = _execution(status="QUEUED", created=600, started=None, heartbeat=None, updated=600)
    result = diagnose(execution, now=now, settings=get_settings())
    assert result.verdict == "WAITING_TOO_LONG"
    assert result.recommendation == "NOTIFY_OPERATOR"
    assert result.queued_seconds == 600


def test_document_tasks_use_longer_stall_window():
    execution, now = _execution(status="RUNNING", updated=400)
    execution.task_type = "documents.ingest"
    settings = get_settings()
    assert settings.task_progress_document_stall_seconds > 400
    assert diagnose(execution, now=now, settings=settings).verdict == "OK"
    execution.updated_at = now - timedelta(seconds=settings.task_progress_document_stall_seconds + 10)
    assert diagnose(execution, now=now, settings=settings).verdict == "STALLED"