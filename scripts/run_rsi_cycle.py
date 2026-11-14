"""执行一轮 M3→T3 RSI 闭环巡检与只读对照实验。

功能边界：
1. 自动扫描近期差评与非基础设施失败任务，将未入库候选确定性脱敏后以 `DRAFT` 状态归集入库；
   绝不自动批准用例，绝不自动写入 `prod-regression/cases.json`。
2. 基于失败阶段、差评原因与脱敏纠正建议聚合只读改进提案，不修改系统提示词或工具源码。
3. 当指定 `--run-experiment` 或提供候选 envelope 目录时，自动运行 `eval_harness`（可选）、
   `prompt_experiment`（配对 McNemar 检验）与 `eval_prompt_gate`（envelope 裁决），并将结论
   汇编进统一 Markdown / JSON 报告；绝不自动执行 `--promote-baseline`。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai_agent.quality_operations import rsi_cycle  # noqa: E402
from app.modules.system_management.model import User  # noqa: E402
from scripts import eval_prompt_gate, prompt_experiment, run_eval_suite  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs/evaluation/rsi-cycle-report.json"
DEFAULT_BASELINE_ROOT = ROOT / "docs/evaluation/baselines"
DEFAULT_CANDIDATE_DIR = ROOT / "docs/evaluation/rsi-candidate/envelopes"


def _build_harness_command(
    candidate_dir: Path,
    *,
    suite: str,
    repeat: int,
    workers: int,
    business_shards: int,
    parallel_suites: bool,
    resume: bool,
) -> list[str]:
    """组装候选采样命令；严格复用 eval_harness.py 参数契约。"""
    command = [
        sys.executable,
        str(ROOT / "scripts/eval_harness.py"),
        "--suite", suite,
        "--out-dir", str(candidate_dir),
        "--repeat", str(repeat),
        "--workers", str(workers),
        "--business-shards", str(business_shards),
    ]
    if parallel_suites:
        command.append("--parallel-suites")
    if resume:
        command.append("--resume")
    return command


def _evaluate_candidate_dir(
    candidate_dir: Path,
    *,
    baseline_root: Path,
    baseline_dir: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """对候选 envelope 执行配对统计检验与门禁裁决（只读，不写入基线）。"""
    resolved_baseline = baseline_dir or (baseline_root / eval_prompt_gate.prompt_key())
    if not resolved_baseline.exists():
        return None, None, f"基线目录不存在：{resolved_baseline}"
    if not candidate_dir.exists():
        return None, None, f"候选目录不存在：{candidate_dir}"

    experiment_summary = None
    gate_summary = None
    errors: list[str] = []
    try:
        experiment_summary = prompt_experiment.run(resolved_baseline, candidate_dir)
    except ValueError as exc:
        errors.append(f"对照实验：{exc}")
    try:
        gate_summary = eval_prompt_gate.run_envelope_gate(candidate_dir, baseline_root)
    except ValueError as exc:
        errors.append(f"门禁检查：{exc}")
    return experiment_summary, gate_summary, ("；".join(errors) if errors else None)


def run_cycle(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="回溯扫描天数（1-90）")
    parser.add_argument("--limit", type=int, default=20, help="最多扫描候选数（1-50）")
    parser.add_argument("--include-infra", action="store_true", help="包含基础设施失败候选供审计")
    parser.add_argument("--dry-run", action="store_true", help="仅预览候选与提案，不写入 DRAFT 用例")
    parser.add_argument("--actor", default="SystemAdmin", help="执行候选入库的管理员用户名")
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库候选同步，仅汇总 envelope 实验报告")
    parser.add_argument("--baseline-root", type=Path, default=DEFAULT_BASELINE_ROOT, help="基线根目录")
    parser.add_argument("--baseline-dir", type=Path, default=None, help="指定基线 envelope 目录")
    parser.add_argument("--candidate-dir", type=Path, default=None, help="候选 envelope 目录")
    parser.add_argument("--run-experiment", action="store_true", help="自动运行 eval_harness 生成候选 envelope 后再比对")
    parser.add_argument("--suite", default="all", choices=("all", "routing", "tasks", "business", "prod"), help="实验套件")
    parser.add_argument("--repeat", type=int, default=3, help="候选实验重复采样轮数")
    parser.add_argument("--workers", type=int, default=3, help="business 套件单分片并发数")
    parser.add_argument("--business-shards", type=int, default=1, help="business 套件分片并发数")
    parser.add_argument("--parallel-suites", action="store_true", help="全套件运行时并行调度")
    parser.add_argument("--preflight", action="store_true", help="跑实验前检查真实模型连通性")
    parser.add_argument("--resume", action="store_true", help="复用候选目录已有非污染轮次")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON 报告路径")
    parser.add_argument("--markdown", type=Path, default=None, help="Markdown 报告路径（默认同名 .md）")
    args = parser.parse_args(argv)

    if not 1 <= args.days <= 90:
        parser.error("--days 必须为 1-90")
    if not 1 <= args.limit <= 50:
        parser.error("--limit 必须为 1-50")
    if args.repeat < 1 or args.workers < 1 or args.business_shards < 1:
        parser.error("--repeat / --workers / --business-shards 必须为正整数")

    candidate_dir = args.candidate_dir or (DEFAULT_CANDIDATE_DIR if args.run_experiment else None)
    experiment_summary: dict[str, Any] | None = None
    gate_summary: dict[str, Any] | None = None
    experiment_error: str | None = None
    exit_code = 0

    if args.run_experiment and candidate_dir is not None:
        if args.preflight:
            ok, detail = run_eval_suite.preflight_model()
            if not ok:
                experiment_error = f"模型预检失败：{detail}"
                exit_code = 2
        if experiment_error is None:
            command = _build_harness_command(
                candidate_dir,
                suite=args.suite,
                repeat=args.repeat,
                workers=args.workers,
                business_shards=args.business_shards,
                parallel_suites=args.parallel_suites,
                resume=args.resume,
            )
            completed = subprocess.run(command, cwd=str(ROOT), check=False)
            if completed.returncode != 0:
                experiment_error = f"eval_harness 退出码 {completed.returncode}"
                exit_code = completed.returncode

    if candidate_dir is not None and experiment_error is None:
        experiment_summary, gate_summary, eval_error = _evaluate_candidate_dir(
            candidate_dir,
            baseline_root=args.baseline_root,
            baseline_dir=args.baseline_dir,
        )
        if eval_error:
            experiment_error = eval_error
            if args.run_experiment:
                exit_code = exit_code or 2

    if args.skip_db:
        report: dict[str, Any] = {
            "kind": "rsi_cycle_report",
            "days": args.days,
            "guardrails": {
                "candidate_generation": "DRAFT_ONLY",
                "baseline_auto_promotion": False,
                "prompt_auto_mutation": False,
            },
            "quality_snapshot": {"tasks": 0, "failed_tasks": 0, "feedback": 0, "up": 0, "down": 0, "down_rate": None, "down_on_success": 0},
            "candidate_sync": {"status": "SKIPPED_DB", "scanned": 0, "eligible": 0, "already_tracked": 0, "too_short": 0, "created": 0, "reused": 0, "skipped": 0, "failed": 0, "created_case_keys": []},
            "improvement_proposals": [],
            "experiment": rsi_cycle._compact_experiment(experiment_summary, experiment_error),
            "gate": rsi_cycle._compact_gate(gate_summary),
        }
    else:
        with SessionLocal() as db:
            actor = db.scalar(select(User).where(User.username == args.actor, User.status == "ACTIVE"))
            if actor is None:
                raise RuntimeError(f"管理员账号 {args.actor} 不存在或已停用")
            report = rsi_cycle.build_rsi_cycle_report(
                db,
                actor,
                days=args.days,
                limit=args.limit,
                include_infra=args.include_infra,
                dry_run=args.dry_run,
                experiment_summary=experiment_summary,
                gate_summary=gate_summary,
                experiment_error=experiment_error,
            )

    markdown_path = args.markdown or args.output.with_suffix(".md")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(rsi_cycle.render_rsi_markdown(report), encoding="utf-8")

    print(json.dumps({
        "candidate_sync_status": report["candidate_sync"]["status"],
        "created_drafts": report["candidate_sync"]["created"],
        "proposals": len(report["improvement_proposals"]),
        "experiment_verdict": report["experiment"]["verdict"],
        "gate_verdict": (report.get("gate") or {}).get("verdict"),
        "output": str(args.output),
        "markdown": str(markdown_path),
    }, ensure_ascii=False))
    return exit_code, report


def main(argv: list[str] | None = None) -> int:
    code, _ = run_cycle(argv)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
