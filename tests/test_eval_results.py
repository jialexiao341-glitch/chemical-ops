"""评测结果入库与月度趋势：幂等登记、逐用例稳定性、跨月聚合。"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.modules.ai.model import AIEvalCaseResult, AIEvalRun
from scripts import eval_trend, record_eval_run


def _case(key: str, passes: list[bool], *, safety: bool = False,
          classes: list[str] | None = None) -> dict:
    return {"key": key, "safety": safety, "trials": [
        {"trial": index, "passed": passed,
         "error_classes": [] if passed else sorted(classes or []),
         "failed_checks": [] if passed else ["outcome"]}
        for index, passed in enumerate(passes, start=1)]}


def _envelope(cases: list[dict], *, suite: str = "business",
              generated_at: str = "2026-11-12T02:00:00+00:00",
              verdict: str = "FAILURES") -> dict:
    return {"suite": suite, "model": "deepseek-v4.1-flash", "repeat": 3,
            "code_revision": "rev-1", "dataset_sha256": "ds",
            "generated_at": generated_at, "summary": {"verdict": verdict},
            "cases": cases}


def _write(tmp_path: Path, name: str, envelope: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[AIEvalRun.__table__, AIEvalCaseResult.__table__])
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


def test_record_writes_run_and_case_rows(tmp_path, db):
    envelope = _envelope([
        _case("B001", [True, True, True]),
        _case("B002", [False, True, True]),
        _case("B003", [False], classes=["TRANSIENT_INFRA"]),
    ])
    path = _write(tmp_path, "harness-business.json", envelope)

    result = record_eval_run.record(db, [path], prompt_key="routing@1__planner@1")

    run = db.scalar(select(AIEvalRun))
    assert result["cases"] == 3
    assert result["skipped"] == []
    assert (run.suite, run.repeat_count, run.cases_total) == ("business", 3, 3)
    assert (run.stable_pass, run.unstable, run.no_evidence) == (1, 1, 1)
    assert run.excluded_infra == 1
    assert run.prompt_key == "routing@1__planner@1"

    rows = {row.case_key: row for row in db.scalars(select(AIEvalCaseResult)).all()}
    assert rows["B001"].verdict == "STABLE_PASS"
    assert rows["B002"].verdict == "UNSTABLE"
    assert rows["B003"].verdict == "NO_EVIDENCE"
    assert rows["B002"].failed_checks == ["outcome"]
    assert rows["B003"].excluded_infra == 1


def test_record_is_idempotent_by_content_fingerprint(tmp_path, db):
    path = _write(tmp_path, "harness-business.json", _envelope([_case("B001", [True])]))
    copy = _write(tmp_path, "harness-business-copy.json", _envelope([_case("B001", [True])]))

    first = record_eval_run.record(db, [path])
    second = record_eval_run.record(db, [copy])

    assert len(first["written"]) == 1
    assert second["written"] == []
    assert second["skipped"] == ["harness-business-copy.json"]
    assert len(db.scalars(select(AIEvalRun)).all()) == 1


def test_dry_run_does_not_touch_database(tmp_path):
    path = _write(tmp_path, "harness-tasks.json", _envelope([_case("T01", [True])],
                                                           suite="tasks", verdict="PASS"))

    result = record_eval_run.record(None, [path], dry_run=True)

    assert result["dry_run"] is True
    assert result["written"][0]["suite"] == "tasks"
    assert result["cases"] == 1


def test_trend_groups_by_month_and_keeps_latest(tmp_path, db):
    record_eval_run.record(db, [
        _write(tmp_path, "jan.json", _envelope(
            [_case("B001", [True]), _case("B002", [False])],
            generated_at="2026-01-15T00:00:00+00:00")),
        _write(tmp_path, "feb.json", _envelope(
            [_case("B001", [True])], generated_at="2026-02-15T00:00:00+00:00",
            suite="tasks", verdict="PASS")),
        _write(tmp_path, "mar.json", _envelope(
            [_case("B001", [True]), _case("B002", [True]), _case("B003", [True])],
            generated_at="2026-03-15T00:00:00+00:00")),
    ])

    rows = eval_trend.summarize(eval_trend.load_runs(db), months=2)

    assert [row["month"] for row in rows] == ["2026-03", "2026-02"]
    assert rows[0]["cases"] == 3 and rows[0]["stable_pass"] == 3
    assert rows[1]["cases"] == 1
    assert rows[1]["stable_rate"] == 1.0


def test_trend_weights_rate_by_cases(tmp_path, db):
    record_eval_run.record(db, [
        _write(tmp_path, "big.json", _envelope(
            [_case("B001", [True]), _case("B002", [True]), _case("B003", [True])],
            generated_at="2026-03-01T00:00:00+00:00", verdict="PASS")),
        _write(tmp_path, "small.json", _envelope(
            [_case("B001", [False])], generated_at="2026-03-02T00:00:00+00:00",
            suite="tasks", verdict="FAILURES")),
    ])

    rows = eval_trend.summarize(eval_trend.load_runs(db))

    assert len(rows) == 1
    assert rows[0]["cases"] == 4
    assert rows[0]["stable_rate"] == pytest.approx(0.75)
    assert rows[0]["verdicts"] == {"PASS": 1, "FAILURES": 1}


def test_trend_suite_filter(tmp_path, db):
    record_eval_run.record(db, [
        _write(tmp_path, "b.json", _envelope([_case("B001", [True])],
                                             generated_at="2026-03-01T00:00:00+00:00")),
        _write(tmp_path, "t.json", _envelope([_case("T01", [True])], suite="tasks",
                                             generated_at="2026-03-01T00:00:00+00:00",
                                             verdict="PASS")),
    ])

    rows = eval_trend.summarize(eval_trend.load_runs(db, suite="tasks"))

    assert rows[0]["cases"] == 1
    assert rows[0]["stable_rate"] == 1.0


def test_trend_render_and_cli(tmp_path, db, monkeypatch, capsys):
    record_eval_run.record(db, [
        _write(tmp_path, "a.json", _envelope([_case("B001", [True])],
                                             generated_at="2026-03-01T00:00:00+00:00"))])

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(eval_trend, "SessionLocal", lambda: SessionContext())
    out = tmp_path / "trend.md"
    code = eval_trend.main(["--out", str(out)])

    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "2026-03" in text and "100.0%" in text
    assert "月度趋势" in capsys.readouterr().out