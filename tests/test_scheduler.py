import pytest

from scripts import run_scheduler


def test_run_once_with_retry_succeeds_after_transient_failure(monkeypatch):
    attempts = []
    delays = []

    def fake_run_once():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("temporary failure")
        return {"scanned_count": 2, "created_count": 1}

    monkeypatch.setattr(run_scheduler, "run_once", fake_run_once)
    monkeypatch.setattr(run_scheduler.time, "sleep", delays.append)

    result = run_scheduler.run_once_with_retry(max_attempts=3, retry_delay_seconds=1.5)

    assert result == {"scanned_count": 2, "created_count": 1}
    assert len(attempts) == 3
    assert delays == [1.5, 1.5]


def test_run_once_with_retry_raises_after_attempts_exhausted(monkeypatch):
    attempts = []
    delays = []

    def fake_run_once():
        attempts.append(1)
        raise RuntimeError("persistent failure")

    monkeypatch.setattr(run_scheduler, "run_once", fake_run_once)
    monkeypatch.setattr(run_scheduler.time, "sleep", delays.append)

    with pytest.raises(RuntimeError, match="persistent failure"):
        run_scheduler.run_once_with_retry(max_attempts=2, retry_delay_seconds=0)

    assert len(attempts) == 2
    assert delays == [0]
