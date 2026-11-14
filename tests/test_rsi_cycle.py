"""M3→T3 RSI 候选自动归集、只读改进提案与实验报告编排测试。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError
from app.modules.ai_agent.model import AIAgentTask, AIFeedback, AIRegressionCase
from app.modules.ai_agent.quality_operations import regression_cases, rsi_cycle
from app.modules.system_management.model import User
from scripts import eval_prompt_gate, run_rsi_cycle, run_scheduler


@pytest.fixture
def rsi_db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
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
        conn.execute(text("""
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
        conn.execute(text("""
            CREATE TABLE ai_regression_cases (
                id INTEGER PRIMARY KEY,
                case_key VARCHAR(64) NOT NULL UNIQUE,
                source_task_id VARCHAR(32),
                source_task_hash VARCHAR(64),
                source_prompt_version VARCHAR(100),
                question TEXT NOT NULL,
                expected_execution_mode VARCHAR(16) NOT NULL,
                expected_tasks JSON NOT NULL,
                forbidden_tasks JSON NOT NULL,
                note VARCHAR(500),
                status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
                created_by INTEGER NOT NULL,
                reviewed_by INTEGER,
                reviewed_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
    session = Session(engine, autoflush=False, expire_on_commit=False)
    roles: dict[int, list[str]] = {1: ["SYS_ADMIN"], 2: ["BUYER"]}
    monkeypatch.setattr(regression_cases, "get_user_role_codes", lambda _db, uid: roles.get(uid, []))
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(user_id: int, username: str = "SystemAdmin") -> User:
    return User(id=user_id, username=username, status="ACTIVE", password_hash="x")


def _seed_task(
    db: Session,
    task_id: str,
    *,
    user_id: int = 2,
    question: str,
    status: str = "FAILED",
    error_code: str | None = None,
    tools: list[str] | None = None,
) -> None:
    now = datetime.now()
    trace = [{"action": "call_tool", "tool": tool} for tool in (tools or [])]
    db.add(AIAgentTask(
        id=task_id,
        user_id=user_id,
        status=status,
        revision=0,
        payload={
            "messages": [question],
            "trace": trace,
            "run_meta": {
                "prompt_versions": {"routing": "routing@1-test", "planner": "planner@1-test"},
                "model": {"name": "deepseek-v4.1-flash"},
            },
        },
        reply="测试回复",
        error_code=error_code,
        created_at=now,
        updated_at=now,
    ))


def _write_envelope(path: Path, suite: str, passed_map: dict[str, bool], *, model: str = "deepseek-v4.1-flash") -> None:
    cases = []
    for key, ok in passed_map.items():
        trials = [{"round": i + 1, "passed": ok, "error_classes": []} for i in range(5)]
        cases.append({
            "key": key,
            "name": key,
            "safety": key.startswith("S"),
            "trials": trials,
            "passed": 5 if ok else 0,
            "total": 5,
            "excluded_infra": 0,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "suite": suite,
        "model": model,
        "repeat": 5,
        "prompt_sha256": "abc123",
        "dataset_sha256": "ds123",
        "code_revision": "rev123",
        "cases": cases,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def test_sync_candidate_drafts_requires_admin_redacts_and_is_idempotent(rsi_db: Session):
    admin = _user(1, "SystemAdmin")
    buyer = _user(2, "buyer1")

    _seed_task(
        rsi_db, "t_fb_1",
        question="帮我联系 13800138000 查询采购单 PO20261001 进度",
        status="SUCCEEDED",
        tools=["order.trace_progress"],
    )
    _seed_task(
        rsi_db, "t_fail_1",
        question="查一下上海分仓乙二醇的可用库存和在途",
        status="FAILED",
        error_code="TOOL_ERRORS",
        tools=["inventory.query_available"],
    )
    _seed_task(
        rsi_db, "t_infra_1",
        question="查一下所有仓库库存",
        status="FAILED",
        error_code="WORKER_UNAVAILABLE",
    )
    now = datetime.now()
    rsi_db.add(AIFeedback(
        user_id=2,
        task_id="t_fb_1",
        rating="DOWN",
        reason_code="FACT_ERROR",
        correction="应说明联系手机 13912345678 对应的到货明细缺失",
        created_at=now,
        updated_at=now,
    ))
    rsi_db.commit()

    with pytest.raises(AuthorizationError):
        rsi_cycle.sync_candidate_drafts(rsi_db, buyer)

    dry = rsi_cycle.sync_candidate_drafts(rsi_db, admin, dry_run=True)
    assert dry["status"] == "DRY_RUN"
    assert dry["scanned"] == 2  # WORKER_UNAVAILABLE 默认被过滤
    assert dry["eligible"] == 2
    assert dry["created"] == 0
    assert rsi_db.scalars(select(AIRegressionCase)).all() == []

    first = rsi_cycle.sync_candidate_drafts(rsi_db, admin, dry_run=False)
    assert first["status"] == "SYNCED"
    assert first["created"] == 2
    assert len(first["created_case_keys"]) == 2

    saved_cases = list(rsi_db.scalars(select(AIRegressionCase)).all())
    assert len(saved_cases) == 2
    assert all(row.status == "DRAFT" for row in saved_cases)
    assert all(row.reviewed_by is None and row.reviewed_at is None for row in saved_cases)
    assert all("13800138000" not in row.question for row in saved_cases)
    assert all("[auto-rsi]" in (row.note or "") for row in saved_cases)

    second = rsi_cycle.sync_candidate_drafts(rsi_db, admin, dry_run=False)
    assert second["status"] == "NO_NEW_CANDIDATES"
    assert second["already_tracked"] == 2
    assert second["created"] == 0


def test_build_rsi_cycle_report_clusters_proposals_and_enforces_guardrails(rsi_db: Session):
    admin = _user(1, "SystemAdmin")
    _seed_task(
        rsi_db, "t_route",
        question="把我当前页面的采购申请转成询价单",
        status="FAILED",
        error_code="INTENT_MISMATCH",
    )
    _seed_task(
        rsi_db, "t_tool",
        question="查询丙酮批次质检结果与报告状态",
        status="FAILED",
        error_code="TOOL_ERRORS",
        tools=["quality.query_acceptance"],
    )
    _seed_task(
        rsi_db, "t_ans",
        question="汇总本月采购金额并列出超期订单",
        status="SUCCEEDED",
        tools=["analytics.query"],
    )
    now = datetime.now()
    rsi_db.add_all([
        AIFeedback(
            user_id=2, task_id="t_route", rating="DOWN", reason_code="SCOPE_ERROR",
            correction="应识别成 rfq_draft，不要直接进通用查询", created_at=now, updated_at=now,
        ),
        AIFeedback(
            user_id=2, task_id="t_ans", rating="DOWN", reason_code="FACT_ERROR",
            correction="电话 13800138000 负责人字段未核对，超期单据缺少明细", created_at=now, updated_at=now,
        ),
    ])
    rsi_db.commit()

    report = rsi_cycle.build_rsi_cycle_report(rsi_db, admin, days=7, limit=20)
    assert report["guardrails"] == {
        "candidate_generation": "DRAFT_ONLY",
        "baseline_auto_promotion": False,
        "prompt_auto_mutation": False,
    }
    assert report["candidate_sync"]["created"] == 3
    proposals = {item["target_area"]: item for item in report["improvement_proposals"]}
    assert "routing_prompt" in proposals
    assert "tool_contract" in proposals
    assert "planner_prompt" in proposals
    for item in proposals.values():
        assert item["auto_applied"] is False
        assert item["requires_human_approval"] is True
        assert item["suggested_checks"]
    assert all("13800138000" not in txt for txt in proposals["planner_prompt"]["redacted_corrections"])

    markdown = rsi_cycle.render_rsi_markdown(report)
    assert "DRAFT" in markdown
    assert "13800138000" not in markdown
    assert "--promote-baseline" in markdown


def test_run_rsi_cycle_cli_runs_experiment_without_promote(tmp_path: Path, monkeypatch):
    baseline_root = tmp_path / "baselines"
    key = eval_prompt_gate.prompt_key()
    baseline_dir = baseline_root / key
    candidate_dir = tmp_path / "candidate"

    suites = {
        "routing": {"R01": True, "R02": True, "R03": False, "R04": False, "R05": False, "R06": False, "R07": False, "R08": False, "S01": True},
        "tasks": {"T01": True, "S02": True},
        "business": {"B01": True, "S03": True},
        "prod": {"P01": True},
    }
    for suite, data in suites.items():
        _write_envelope(baseline_dir / f"harness-{suite}.json", suite, data)
        candidate_data = dict(data)
        if suite == "routing":
            for k in ("R03", "R04", "R05", "R06", "R07", "R08"):
                candidate_data[k] = True
        _write_envelope(candidate_dir / f"harness-{suite}.json", suite, candidate_data)

    invoked_commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        invoked_commands.append(list(cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_rsi_cycle.subprocess, "run", fake_run)
    monkeypatch.setattr(run_rsi_cycle.run_eval_suite, "preflight_model", lambda: (True, "ok"))

    output_json = tmp_path / "out/rsi-cycle-report.json"
    code, report = run_rsi_cycle.run_cycle([
        "--skip-db",
        "--run-experiment",
        "--preflight",
        "--baseline-root", str(baseline_root),
        "--candidate-dir", str(candidate_dir),
        "--business-shards", "2",
        "--parallel-suites",
        "--output", str(output_json),
    ])
    assert code == 0
    assert invoked_commands and "--business-shards" in invoked_commands[0]
    assert "--parallel-suites" in invoked_commands[0]
    assert report["experiment"]["status"] == "COMPLETED"
    assert report["experiment"]["verdict"] == "IMPROVED"
    assert report["gate"]["verdict"] == "PASS"
    assert report["guardrails"]["baseline_auto_promotion"] is False
    assert output_json.exists()
    assert output_json.with_suffix(".md").exists()

    # 确认脚本不开放自动写基线入口
    with pytest.raises(SystemExit):
        run_rsi_cycle.run_cycle(["--skip-db", "--promote-baseline"])


def test_scheduler_run_once_isolates_rsi_sync_failure(monkeypatch):
    class _FakeDb:
        def __init__(self):
            self.rolled_back = False
            self.closed = False

        def scalar(self, *_args, **_kwargs):
            return SimpleNamespace(id=1, username="SystemAdmin", status="ACTIVE")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    fake_db = _FakeDb()
    monkeypatch.setattr(run_scheduler, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(run_scheduler, "scan_overdue_deliveries", lambda *_args, **_kwargs: {"scanned_count": 3})
    monkeypatch.setattr(run_scheduler, "recover_stale_parses", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        run_scheduler,
        "sync_candidate_drafts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rsi table unavailable")),
    )

    res = run_scheduler.run_once()
    assert res["scanned_count"] == 3
    assert res["recovered_file_parse_count"] == 1
    assert res["rsi_candidate_drafts_created"] == 0
    assert fake_db.rolled_back is True
    assert fake_db.closed is True
