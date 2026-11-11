"""统一评测 harness：多轮采样、断点续跑、统一 envelope 与失败分类。

四个既有评测脚本保持独立可运行；本脚本只负责编排与汇总，不改写历史报告。
envelope 结构：
    {
      "suite", "generated_at", "model", "prompt_sha256", "code_revision",
      "dataset_sha256", "repeat",
      "cases": [{"key", "trials": [{"trial", "passed", "status", "error_classes"}]}],
      "summary": {"total", "passed", "failed", "infra_failed", "verdict"}
    }

退出码：0 全部通过；1 存在实现失败；2 仅剩基础设施失败（本轮不可作证据）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TRIAL_SUFFIX = ".trial-{index}.json"

SUITES = ("routing", "tasks", "business", "prod")

# 与 compare_eval_reports 保持一致：仅该类失败不计实现退化。
INFRA_ERROR_CLASSES = {"TRANSIENT_INFRA"}


def trial_path(out: Path, index: int) -> Path:
    """每轮写独立文件，便于断点续跑与事后核对。"""
    return out.with_name(out.stem + TRIAL_SUFFIX.format(index=index))


def build_command(suite: str, out: Path, *, workers: int) -> list[str]:
    """按套件拼评测命令；参数只做最小必要传递，其余沿用脚本默认值。"""
    if suite == "routing":
        return [PYTHON, str(ROOT / "scripts/evaluate_intent_routing.py"),
                "--output", str(out), "--repeats", "1"]
    if suite == "tasks":
        return [PYTHON, str(ROOT / "scripts/evaluate_agent_tasks.py"), "--output", str(out)]
    if suite == "business":
        return [PYTHON, str(ROOT / "scripts/evaluate_agent_business.py"),
                "--output", str(out), "--repetitions", "1", "--workers", str(workers)]
    if suite == "prod":
        return [PYTHON, str(ROOT / "scripts/evaluate_prod_regression.py"),
                "--cases", str(ROOT / "docs/evaluation/prod-regression/cases.json"),
                "--output", str(out)]
    raise ValueError(f"未知套件：{suite}")


def _case_key(row: dict) -> str:
    if row.get("id") is not None:
        return str(row["id"])
    if row.get("question") is not None:
        return str(row["question"])
    raise ValueError("用例缺少 id 与 question，无法建立稳定键")


def _error_classes(row: dict) -> set[str]:
    """汇总用例行与各轮 run_meta.error.class。"""
    classes: set[str] = set()
    metas = [row.get("run_meta") or {}]
    metas += [(round_data.get("run_meta") or {}) for round_data in (row.get("rounds") or [])
              if isinstance(round_data, dict)]
    for meta in metas:
        error = meta.get("error")
        if isinstance(error, dict) and error.get("class"):
            classes.add(str(error["class"]))
    return classes


def merge_trials(suite: str, reports: list[dict], repeat: int) -> dict:
    """把多轮原始报告合成 envelope；同一 key 的每轮结果都保留。"""
    cases: dict[str, dict] = {}
    for index, report in enumerate(reports, start=1):
        rows = [row for row in (report.get("cases") or []) if isinstance(row, dict)]
        for row in rows:
            key = _case_key(row)
            entry = cases.setdefault(key, {"key": key, "trials": []})
            entry["trials"].append({
                "trial": index,
                "passed": bool(row.get("passed")),
                "status": row.get("status"),
                "error_classes": sorted(_error_classes(row)),
            })
    ordered = list(cases.values())
    passed = [entry for entry in ordered if all(t["passed"] for t in entry["trials"])]
    failed = [entry for entry in ordered if entry not in passed]
    infra_only = [entry for entry in failed
                  if all(set(t["error_classes"]) and set(t["error_classes"]) <= INFRA_ERROR_CLASSES
                         for t in entry["trials"] if not t["passed"])]
    if not failed:
        verdict = "PASS"
    elif len(infra_only) == len(failed):
        verdict = "INVALID_RUN"
    else:
        verdict = "FAILURES"
    meta_source = next((r for r in reports if r.get("model") or r.get("code_revision")), {})
    return {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repeat": repeat,
        "model": meta_source.get("model"),
        "prompt_sha256": meta_source.get("prompt_sha256") or meta_source.get("planner_sha256"),
        "code_revision": meta_source.get("code_revision"),
        "dataset_sha256": meta_source.get("dataset_sha256"),
        "cases": ordered,
        "summary": {
            "total": len(ordered),
            "passed": len(passed),
            "failed": len(failed),
            "infra_failed": len(infra_only),
            "verdict": verdict,
        },
    }


def _default_runner(command: list[str], out: Path) -> dict:
    """评测脚本在有用例失败时也返回 1，只有报告缺失才算运行失败。"""
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
    if not out.exists():
        raise RuntimeError(
            f"评测未生成报告（退出码 {completed.returncode}）："
            f"{(completed.stderr or completed.stdout or '').strip()[:400]}")
    return json.loads(out.read_text(encoding="utf-8"))


def run(suite: str, out: Path, *, repeat: int = 1, workers: int = 2, resume: bool = False,
        runner=None) -> dict:
    """执行（或在 resume 时复用）每轮报告，再合成 envelope 并落盘。"""
    if repeat < 1:
        raise ValueError("repeat 必须为正数")
    runner = runner or _default_runner
    reports: list[dict] = []
    for index in range(1, repeat + 1):
        path = trial_path(out, index)
        if resume and path.exists():
            reports.append(json.loads(path.read_text(encoding="utf-8")))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        reports.append(runner(build_command(suite, path, workers=workers), path))
    envelope = merge_trials(suite, reports, repeat)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return envelope


def render_text(envelope: dict) -> str:
    summary = envelope["summary"]
    return "\n".join([
        f"套件：{envelope['suite']}  重复：{envelope['repeat']} 次",
        f"模型：{envelope.get('model') or '—'}  代码：{envelope.get('code_revision') or '—'}",
        f"用例：{summary['passed']}/{summary['total']} 通过；"
        f"失败 {summary['failed']} 条，其中基础设施 {summary['infra_failed']} 条",
        f"判定：{summary['verdict']}",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--out", type=Path, required=True, help="envelope 输出路径")
    parser.add_argument("--repeat", type=int, default=1, help="同一套件重复采样次数")
    parser.add_argument("--workers", type=int, default=2, help="business 套件并发数")
    parser.add_argument("--resume", action="store_true", help="复用已有 trial 报告，只补缺失轮次")
    parser.add_argument("--json", action="store_true", help="输出 envelope JSON")
    args = parser.parse_args(argv)
    try:
        envelope = run(args.suite, args.out, repeat=args.repeat,
                       workers=args.workers, resume=args.resume)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"评测失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(envelope, ensure_ascii=False, indent=2) if args.json else render_text(envelope))
    verdict = envelope["summary"]["verdict"]
    return 0 if verdict == "PASS" else (2 if verdict == "INVALID_RUN" else 1)


if __name__ == "__main__":
    raise SystemExit(main())