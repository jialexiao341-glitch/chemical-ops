"""按当前 prompt 版本校验候选评测报告；缺基线或存在回归时拒绝通过。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.modules.ai import prompt_registry  # noqa: E402
from scripts import compare_eval_reports  # noqa: E402


REPORT_FILES = {
    "intent_routing": "intent_routing.json",
    "agent_tasks": "agent_tasks.json",
    "agent_business": "agent_business.json",
    "prod_regression": "prod_regression.json",
}

PYTHON = sys.executable

# 只支持按编号重跑单例的套件；路由套件没有单例参数，回归项只能整轮重跑。
RETEST_COMMANDS = {
    "agent_tasks": lambda key, out: [
        PYTHON, str(ROOT / "scripts/evaluate_agent_tasks.py"),
        "--cases", key, "--output", str(out)],
    "agent_business": lambda key, out: [
        PYTHON, str(ROOT / "scripts/evaluate_agent_business.py"),
        "--cases", key, "--repetitions", "1", "--workers", "1", "--output", str(out)],
    "prod_regression": lambda key, out: [
        PYTHON, str(ROOT / "scripts/evaluate_prod_regression.py"),
        "--cases", str(ROOT / "docs/evaluation/prod-regression/cases.json"),
        "--only", key, "--output", str(out)],
}


def prompt_key() -> str:
    """路由或规划提示词任一变化都必须重新登记基线。"""
    return f"{prompt_registry.prompt_version('routing')}__{prompt_registry.prompt_version('planner')}"


def run_gate(candidate_dir: Path, baseline_root: Path) -> dict:
    """对比候选目录与当前 prompt 版本基线；缺报告即 NOT_RUN，不允许子集冒充全量。"""
    key = prompt_key()
    baseline_dir = baseline_root / key
    reports = []
    present: list[str] = []
    missing: list[str] = []
    for name, filename in REPORT_FILES.items():
        candidate = candidate_dir / filename
        if not candidate.exists():
            missing.append(name)
            continue
        present.append(name)
        baseline = baseline_dir / filename
        if not baseline.exists():
            raise ValueError(
                f"缺少当前 prompt 版本 {key} 的基线 {filename}；"
                "请先审阅候选报告并执行 --promote-baseline"
            )
        result = compare_eval_reports.compare(
            compare_eval_reports.load_report(baseline),
            compare_eval_reports.load_report(candidate),
        )
        reports.append({
            "name": name,
            "verdict": result["verdict"],
            "baseline_passed": result["baseline"]["passed"],
            "baseline_total": result["baseline"]["total"],
            "candidate_passed": result["candidate"]["passed"],
            "candidate_total": result["candidate"]["total"],
            "regressions": [row["key"] for row in result["regressions"]],
            "infra_failures": [row["key"] for row in result.get("infra_failures", [])],
            "safety_failures": [row["key"] for row in result["safety_failures"]],
        })
    if not reports:
        raise ValueError(f"候选目录 {candidate_dir} 没有可对比的评测报告")
    if missing:
        verdict = "NOT_RUN"
    elif any(row["verdict"] == "REGRESSION" for row in reports):
        verdict = "REGRESSION"
    elif any(row["verdict"] == "INVALID_RUN" for row in reports):
        verdict = "INVALID_RUN"
    else:
        verdict = "PASS"
    return {"prompt_key": key, "baseline_dir": str(baseline_dir),
            "candidate_dir": str(candidate_dir), "reports": reports,
            "coverage": {"present": present, "missing": missing,
                         "required": list(REPORT_FILES),
                         "note": "四份报告必须全部重跑；缺少任一报告判定 NOT_RUN，不能按已跑部分判 PASS"},
            "verdict": verdict}


def _case_passed(report: dict, key: str) -> bool:
    for row in report.get("cases") or []:
        if isinstance(row, dict) and (row.get("id") == key or row.get("key") == key):
            return bool(row.get("passed"))
    raise ValueError(f"重跑报告中找不到用例 {key}")


def _default_runner(command: list[str], timeout: int = 900) -> dict:
    """重跑单例；评测脚本在用例失败时也返回非零，退出码本身不代表执行失败。"""
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    output = Path(command[command.index("--output") + 1])
    if not output.exists():
        raise RuntimeError(
            f"重跑未生成报告（退出码 {completed.returncode}）："
            f"{(completed.stderr or completed.stdout or '').strip()[:500]}")
    return json.loads(output.read_text(encoding="utf-8"))


def retest_regressions(candidate_dir: Path, result: dict, *, attempts: int = 3,
                       runner=None) -> dict:
    """对判为回归的用例按编号重跑，区分稳定回归与单次采样波动。

    评测是真实模型采样，同一 prompt 版本下单次 FAIL 不能直接当作实现回归；
    回归项多数次重跑通过时记为 FLAKY，仍需人工在报告中留痕。
    """
    if attempts < 3:
        raise ValueError("重跑次数至少为 3，否则无法区分波动与稳定回归")
    runner = runner or _default_runner
    retests: list[dict] = []
    changed = False
    for row in result["reports"]:
        if row["verdict"] != "REGRESSION" or row.get("safety_failures"):
            continue
        build = RETEST_COMMANDS.get(row["name"])
        if build is None:
            retests.append({"name": row["name"], "keys": row["regressions"],
                            "supported": False,
                            "note": "该套件不支持按编号重跑，需整轮重跑后重新判定"})
            continue
        verdicts = []
        for key in row["regressions"]:
            passes = 0
            for index in range(attempts):
                out = candidate_dir / f"retest-{row['name']}-{key}-{index + 1}.json"
                passes += int(_case_passed(runner(build(key, out)), key))
            flaky = passes >= attempts // 2 + 1
            verdicts.append({"key": key, "attempts": attempts, "passes": passes,
                             "verdict": "FLAKY" if flaky else "REGRESSION"})
        retests.append({"name": row["name"], "supported": True,
                        "keys": verdicts, "attempts": attempts})
        changed = True
        if all(item["verdict"] == "FLAKY" for item in verdicts):
            row["verdict"] = "FLAKY"
        else:
            row["verdict"] = "REGRESSION"
            row["stable_regressions"] = [item["key"] for item in verdicts
                                         if item["verdict"] == "REGRESSION"]
    if changed:
        if any(row["verdict"] == "REGRESSION" for row in result["reports"]):
            result["verdict"] = "REGRESSION"
        elif any(row["verdict"] == "INVALID_RUN" for row in result["reports"]):
            result["verdict"] = "INVALID_RUN"
        elif any(row.get("infra_failures") for row in result["reports"]):
            # 复核只修得清回归项；整轮里成片的基础设施失败说明本轮证据不可用。
            result["verdict"] = "INVALID_RUN"
        elif any(row["verdict"] == "FLAKY" for row in result["reports"]):
            result["verdict"] = "FLAKY"
    result["retests"] = retests
    return result


def _report_versions(data: dict) -> dict[str, list[str]]:
    """从报告中收集实际使用的 prompt 版本；同一报告出现多版本时全部保留。"""
    seen: dict[str, set[str]] = {}
    top = data.get("prompt_versions")
    if isinstance(top, dict):
        for name, version in top.items():
            if isinstance(version, str) and version:
                seen.setdefault(str(name), set()).add(version)
    for row in data.get("cases") or []:
        if not isinstance(row, dict):
            continue
        rounds = row.get("rounds") or []
        for round_data in rounds:
            if not isinstance(round_data, dict):
                continue
            versions = ((round_data.get("run_meta") or {}).get("prompt_versions") or {})
            for name, version in versions.items():
                if isinstance(version, str) and version:
                    seen.setdefault(str(name), set()).add(version)
        versions = (row.get("run_meta") or {}).get("prompt_versions") or {}
        for name, version in versions.items():
            if isinstance(version, str) and version:
                seen.setdefault(str(name), set()).add(version)
    result = {name: sorted(values) for name, values in sorted(seen.items())}
    sha = data.get("prompt_sha256")
    if isinstance(sha, str) and sha:
        result.setdefault("routing_sha256", [sha])
    return result


def promote_baseline(candidate_dir: Path, baseline_root: Path, *, force: bool = False) -> dict:
    """把候选报告登记为当前 prompt 版本基线；覆盖已有基线需 --force。

    候选报告可能只重跑了部分套件，其余报告从上一版本延用。manifest 记录每份
    报告实际使用的 prompt 版本和未重跑项，避免把旧证据当成当前版本证据。
    """
    key = prompt_key()
    target = baseline_root / key
    existing = [name for name in REPORT_FILES.values() if (target / name).exists()]
    if existing and not force:
        raise ValueError(f"当前 prompt 版本已有基线（{', '.join(existing)}）；覆盖需 --force")
    files = [name for name in REPORT_FILES.values() if (candidate_dir / name).exists()]
    missing = [name for name in REPORT_FILES.values() if name not in files]
    if not files:
        raise ValueError(f"候选目录 {candidate_dir} 没有可登记报告")
    target.mkdir(parents=True, exist_ok=True)
    report_versions = {
        name: _report_versions(json.loads((candidate_dir / name).read_text(encoding="utf-8")))
        for name in files
    }
    current = {"routing": prompt_registry.prompt_version("routing"),
               "planner": prompt_registry.prompt_version("planner")}
    carried_forward = [
        {"file": name, "versions": {prompt: versions for prompt, versions in versions.items()
                                    if prompt in current and versions != [current[prompt]]}}
        for name, versions in report_versions.items()
    ]
    carried_forward = [item for item in carried_forward if item["versions"]]
    for name in files:
        shutil.copyfile(candidate_dir / name, target / name)
    manifest = {
        "prompt_key": key,
        "routing_version": prompt_registry.prompt_version("routing"),
        "planner_version": prompt_registry.prompt_version("planner"),
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "files": files,
        "coverage": {"files": files, "missing": missing,
                     "note": "只登记候选目录实际存在的报告；未重跑项在 coverage.missing 中显式留痕"},
        "report_versions": report_versions,
        "carried_forward": carried_forward,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"prompt_key": key, "baseline_dir": str(target), "files": files,
            "coverage": manifest["coverage"],
            "report_versions": report_versions, "carried_forward": carried_forward}


def render_text(result: dict) -> str:
    lines = [f"prompt 版本：{result['prompt_key']}", f"基线目录：{result['baseline_dir']}"]
    for row in result["reports"]:
        lines.append(
            f"- {row['name']}：{row['baseline_passed']}/{row['baseline_total']} → "
            f"{row['candidate_passed']}/{row['candidate_total']}，{row['verdict']}"
        )
        if row["regressions"]:
            lines.append("  回归：" + "、".join(row["regressions"]))
        if row.get("infra_failures"):
            lines.append("  基础设施失败：" + "、".join(row["infra_failures"]))
        if row["safety_failures"]:
            lines.append("  安全失败：" + "、".join(row["safety_failures"]))
    lines.append(f"判定：{result['verdict']}")
    verdict_notes = {
        "INVALID_RUN": "（存在基础设施失败，本轮不可作基线证据，需重跑取证）",
        "NOT_RUN": "（报告不全，按子集不能判通过）",
    }
    if result["verdict"] in verdict_notes:
        lines.append("说明：" + verdict_notes[result["verdict"]])
    coverage = result.get("coverage") or {}
    if coverage.get("missing"):
        lines.append("覆盖度：缺少 " + "、".join(coverage["missing"]) + "（未判定 PASS）")
    for retest in result.get("retests") or []:
        if not retest.get("supported"):
            lines.append(f"复核：{retest['name']} 不支持单例重跑（{'、'.join(retest['keys'])}）")
            continue
        detail = "、".join(f"{item['key']} {item['passes']}/{item['attempts']} {item['verdict']}"
                          for item in retest["keys"])
        lines.append(f"复核：{retest['name']} {detail}")
        if any(item["verdict"] == "FLAKY" for item in retest["keys"]):
            lines.append("  含 FLAKY：单次采样波动，非实现回归；仍需人工确认后重跑整轮取证")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path,
                        default=ROOT / "docs/evaluation/candidate", help="候选报告目录")
    parser.add_argument("--baseline-root", type=Path,
                        default=ROOT / "docs/evaluation/baselines", help="基线根目录")
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="存在回归、安全失败或覆盖度不足（NOT_RUN）时返回 2")
    parser.add_argument("--promote-baseline", action="store_true",
                        help="把候选报告登记为当前 prompt 版本基线")
    parser.add_argument("--force", action="store_true", help="覆盖已有基线")
    parser.add_argument("--retest-attempts", type=int, default=0,
                        help="对回归用例按编号重跑 N 次（≥3）复核是否为采样波动")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    try:
        if args.promote_baseline:
            result = promote_baseline(args.candidate_dir, args.baseline_root, force=args.force)
            print(json.dumps(result, ensure_ascii=False) if args.json else
                  f"已登记基线：{result['baseline_dir']}（{', '.join(result['files'])}）")
            if not args.json:
                for item in result["carried_forward"]:
                    detail = "、".join(f"{name}={','.join(versions)}"
                                       for name, versions in item["versions"].items())
                    print(f"注意：{item['file']} 延用旧版本报告（{detail}），需在报告中保留说明")
            return 0
        result = run_gate(args.candidate_dir, args.baseline_root)
        if args.retest_attempts and result["verdict"] == "REGRESSION":
            result = retest_regressions(args.candidate_dir, result,
                                        attempts=args.retest_attempts)
    except (OSError, ValueError) as exc:
        print(f"评测门禁失败：{exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_text(result))
    if args.fail_on_regression and result["verdict"] in {"REGRESSION", "NOT_RUN", "INVALID_RUN"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())