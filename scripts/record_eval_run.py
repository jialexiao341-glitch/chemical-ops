"""把 harness envelope 写入评测结果库；同一 envelope 按文件指纹幂等跳过。

登记的是稳定性结果（逐用例有效轮次、判定、排除的基础设施轮次），不写模型原文，
不产生新的模型调用；重复执行 `--dir` 不会重复计数。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai_agent.model import AIEvalCaseResult, AIEvalRun  # noqa: E402
from scripts import eval_stability  # noqa: E402


def envelope_paths(directory: Path) -> list[Path]:
    """只取套件 envelope；trial 原始报告不单独入库。"""
    paths = sorted(path for path in directory.glob("harness-*.json")
                   if ".trial-" not in path.name)
    if not paths:
        raise ValueError(f"目录 {directory} 没有 harness-<suite>.json")
    return paths


def collected_at(envelope: dict) -> datetime:
    """envelope 生成时间转 UTC naive，跨库按月份分组时不受本地时区影响。"""
    raw = envelope.get("generated_at")
    try:
        moment = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.now()
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def case_failed_checks(case: dict) -> list[str]:
    checks = set()
    for trial in case.get("trials") or []:
        if isinstance(trial, dict) and not trial.get("passed"):
            checks.update(str(name) for name in (trial.get("failed_checks") or []))
    return sorted(checks)


def case_payload(case: dict) -> dict:
    passed, total, excluded, verdict = eval_stability.classify_case(case)
    return {
        "case_key": str(case.get("key"))[:191],
        "safety": bool(case.get("safety")),
        "trials": total,
        "passed": passed,
        "excluded_infra": excluded,
        "verdict": verdict,
        "failed_checks": case_failed_checks(case),
    }


def build_run(envelope: dict, fingerprint: str, *, prompt_key: str = "") -> tuple[AIEvalRun, list[dict]]:
    cases = [case for case in (envelope.get("cases") or []) if isinstance(case, dict)]
    payloads = [case_payload(case) for case in cases]
    counts = Counter(payload["verdict"] for payload in payloads)
    run = AIEvalRun(
        envelope_sha256=fingerprint,
        suite=str(envelope.get("suite") or "unknown")[:16],
        prompt_key=prompt_key or None,
        model=(str(envelope.get("model"))[:64] if envelope.get("model") else None),
        code_revision=(str(envelope.get("code_revision"))[:64]
                       if envelope.get("code_revision") else None),
        dataset_sha256=(str(envelope.get("dataset_sha256"))[:64]
                        if envelope.get("dataset_sha256") else None),
        repeat_count=int(envelope.get("repeat") or 1),
        cases_total=len(payloads),
        stable_pass=counts.get("STABLE_PASS", 0),
        unstable=counts.get("UNSTABLE", 0),
        stable_fail=counts.get("STABLE_FAIL", 0),
        no_evidence=counts.get(eval_stability.NO_EVIDENCE, 0),
        excluded_infra=sum(payload["excluded_infra"] for payload in payloads),
        verdict=str((envelope.get("summary") or {}).get("verdict") or "UNKNOWN")[:16],
        collected_at=collected_at(envelope),
        created_at=datetime.now(),
    )
    return run, payloads


def record(db, paths: list[Path], *, prompt_key: str = "", dry_run: bool = False) -> dict:
    """逐文件登记；已登记的 envelope 指纹跳过，新结果与逐用例行一次性提交。"""
    written: list[dict] = []
    skipped: list[str] = []
    cases = 0
    for path in paths:
        raw = path.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        if not dry_run and db.scalar(
                select(AIEvalRun.id).where(AIEvalRun.envelope_sha256 == fingerprint)) is not None:
            skipped.append(path.name)
            continue
        envelope = json.loads(raw)
        run, payloads = build_run(envelope, fingerprint, prompt_key=prompt_key)
        if not dry_run:
            db.add(run)
            db.flush()
            for payload in payloads:
                db.add(AIEvalCaseResult(run_id=run.id, **payload))
        written.append({"file": path.name, "suite": run.suite, "cases": run.cases_total,
                        "stable_pass": run.stable_pass, "unstable": run.unstable,
                        "stable_fail": run.stable_fail, "verdict": run.verdict})
        cases += run.cases_total
    if not dry_run:
        db.commit()
    return {"written": written, "skipped": skipped, "cases": cases, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path,
                        default=ROOT / "docs/evaluation/candidate/envelopes",
                        help="含 harness-<suite>.json 的目录")
    parser.add_argument("--prompt-key", default="", help="登记到 ai_eval_runs.prompt_key")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写数据库")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    try:
        paths = envelope_paths(args.dir)
        if args.dry_run:
            result = record(None, paths, prompt_key=args.prompt_key, dry_run=True)
        else:
            with SessionLocal() as db:
                result = record(db, paths, prompt_key=args.prompt_key)
    except (OSError, ValueError) as exc:
        print(f"登记失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          f"登记 {len(result['written'])} 份，跳过 {len(result['skipped'])} 份，"
          f"用例 {result['cases']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())