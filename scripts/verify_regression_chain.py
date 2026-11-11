"""回归用例全链路验收：任务 → 草稿 → 审批 → 用例 → 导出 → 门禁 → 基线，全部在隔离 SQLite 上重放。

不连接业务库、不调用模型；只验证确定性代码路径并把每一步的实际输出写入证据文件。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.modules.ai import regression_cases  # noqa: E402
from app.modules.ai.model import AIAgentTask, AIFeedback, AIRegressionCase  # noqa: E402
from app.modules.ai.schema import RegressionCaseCreate  # noqa: E402
from app.modules.system.model import User  # noqa: E402
from scripts import eval_prompt_gate as gate  # noqa: E402
from scripts.export_regression_cases import case_payload, merge_cases  # noqa: E402

DDL = (
    """
    CREATE TABLE ai_agent_tasks (
        id VARCHAR(32) PRIMARY KEY, user_id INTEGER NOT NULL, status VARCHAR(24) NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0, payload JSON NOT NULL, reply TEXT NOT NULL,
        error_code VARCHAR(64), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE ai_feedback (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, task_id VARCHAR(32) NOT NULL,
        rating VARCHAR(8) NOT NULL, reason_code VARCHAR(32), comment VARCHAR(1000),
        correction TEXT, prompt_version VARCHAR(100), prompt_versions JSON,
        model_name VARCHAR(100), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE ai_regression_cases (
        id INTEGER PRIMARY KEY, case_key VARCHAR(64) NOT NULL UNIQUE, source_task_id VARCHAR(32),
        source_task_hash VARCHAR(64), source_prompt_version VARCHAR(100), question TEXT NOT NULL,
        expected_execution_mode VARCHAR(16) NOT NULL, expected_tasks JSON NOT NULL,
        forbidden_tasks JSON NOT NULL, note VARCHAR(500), status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
        created_by INTEGER NOT NULL, reviewed_by INTEGER, reviewed_at DATETIME,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )
    """,
)


def _passing_report() -> dict:
    return {"cases": [{"id": "T01", "passed": True, "checks": {"outcome": True}}]}


def run(output: Path) -> dict:
    """执行七步链路并返回可复核的结构化证据。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in DDL:
            connection.execute(text(statement))
    db = Session(engine, autoflush=False, expire_on_commit=False)
    roles: dict[int, list[str]] = {}
    original_roles = regression_cases.get_user_role_codes
    regression_cases.get_user_role_codes = lambda _db, user_id: roles.get(user_id, [])
    workdir: Path | None = None
    try:
        now = datetime.now()
        db.add(AIAgentTask(
            id="task-p1", user_id=1, status="FAILED", revision=0,
            payload={"messages": ["查乙醇库存并统计本月采购订单金额"],
                     "run_meta": {"prompt_versions": {"routing": "routing@1-p1",
                                                      "planner": "planner@1-p1"},
                                  "model": {"name": "deepseek-v4.1-flash"}},
                     "trace": [{"action": "call_tool", "tool": "inventory.query_available"}]},
            reply="", error_code="INTENT_SCHEMA_ERROR", created_at=now, updated_at=now))
        db.add(AIFeedback(id=1, user_id=1, task_id="task-p1", rating="DOWN",
                          reason_code="WRONG_NUMBER", comment=None, correction=None,
                          prompt_version="routing@1-p1", prompt_versions=None,
                          model_name="deepseek-v4.1-flash", created_at=now, updated_at=now))
        db.commit()

        owner = User(id=1, username="owner", status="ACTIVE", password_hash="x")
        admin = User(id=2, username="admin", status="ACTIVE", password_hash="x")
        roles[2] = ["SYS_ADMIN"]

        candidates = regression_cases.candidate_drafts(db, owner, days=7, limit=10)
        item = candidates.items[0]

        case = regression_cases.create_case(db, owner, RegressionCaseCreate(
            source_task_id=item.source_task_id,
            question="查【已脱敏产品】库存并统计本月采购订单金额",
            expected_execution_mode=item.expected_execution_mode,
            expected_tasks=item.expected_tasks,
            note=f"来源：{item.source}；失败阶段：{item.failure_stage}",
            redacted_confirmed=True))
        approved = regression_cases.review_case(db, admin, case.id, "APPROVE")
        exported = case_payload(db.get(AIRegressionCase, case.id))
        merged = merge_cases([{"id": "PR-manual", "question": "手工用例", "note": ""}], [exported])

        workdir = Path(tempfile.mkdtemp(prefix="p1-chain-"))
        baseline_root = workdir / "baselines"
        full_candidate = workdir / "candidate-full"
        subset_candidate = workdir / "candidate-subset"
        key = gate.prompt_key()
        for name in gate.REPORT_FILES.values():
            for directory in (baseline_root / key, full_candidate):
                directory.mkdir(parents=True, exist_ok=True)
                (directory / name).write_text(json.dumps(_passing_report()), encoding="utf-8")
        subset_candidate.mkdir(parents=True, exist_ok=True)
        (subset_candidate / "intent_routing.json").write_text(
            json.dumps(_passing_report()), encoding="utf-8")

        full = gate.run_gate(full_candidate, baseline_root)
        subset = gate.run_gate(subset_candidate, baseline_root)
        promoted = gate.promote_baseline(full_candidate, baseline_root, force=True)
        manifest = json.loads(
            (Path(promoted["baseline_dir"]) / "manifest.json").read_text(encoding="utf-8"))

        artifact = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "scope": "隔离 SQLite；真实模型未调用，业务库未连接",
            "stages": {
                "task": {"id": "task-p1", "status": "FAILED",
                         "error_code": "INTENT_SCHEMA_ERROR",
                         "question_redacted": True},
                "feedback": {"rating": "DOWN", "reason_code": "WRONG_NUMBER"},
                "candidate": {"total": candidates.total, "source": item.source,
                              "case_key": item.case_key, "failure_stage": item.failure_stage,
                              "existing_case_id": item.existing_case_id},
                "create": {"id": case.id, "status": case.status},
                "approve": {"id": approved.id, "status": approved.status,
                            "reviewed_by": approved.reviewed_by},
                "export": {"id": exported["id"], "has_source_task_id": "source_task_id" in exported,
                           "merged_total": len(merged),
                           "merged_ids": [row["id"] for row in merged]},
                "candidate_after_approve": {
                    "existing_case_id": regression_cases.candidate_drafts(
                        db, owner, days=7, limit=10).items[0].existing_case_id},
                "gate": {"full": full["verdict"], "subset": subset["verdict"],
                         "subset_missing": subset["coverage"]["missing"]},
                "baseline": {"files": promoted["files"],
                             "coverage_missing": manifest["coverage"]["missing"],
                             "manifest_prompt_key": manifest["prompt_key"]},
            },
        }
    finally:
        regression_cases.get_user_role_codes = original_roles
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
        db.close()
        engine.dispose()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/p1-chain/chain.json")
    args = parser.parse_args(argv)
    artifact = run(args.output)
    print(json.dumps({"verdict": artifact["stages"]["gate"],
                      "baseline": artifact["stages"]["baseline"],
                      "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())