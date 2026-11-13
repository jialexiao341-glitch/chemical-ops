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

from app.modules.ai_agent import prompt_registry  # noqa: E402
from scripts import compare_eval_reports  # noqa: E402
from scripts import eval_stability  # noqa: E402


REPORT_FILES = {
    "intent_routing": "intent_routing.json",
    "agent_tasks": "agent_tasks.json",
    "agent_business": "agent_business.json",
    "prod_regression": "prod_regression.json",
}

# envelope 模式：直接消费 eval_harness 的产物，判定口径与 eval_stability 相同。
ENVELOPE_SUITES = ("routing", "tasks", "business", "prod")
ENVELOPE_FILES = tuple(f"harness-{suite}.json" for suite in ENVELOPE_SUITES)

# 少于该轮次时 Wilson 区间过宽，只能区分“全过/全败”，不能给出统计结论。
MIN_STATISTICAL_TRIALS = 5

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


def envelope_path(root: Path, suite: str) -> Path:
    """与 eval_harness.suite_envelope_path 保持同一命名，避免两处各写一套路径。"""
    return root / f"harness-{suite}.json"


def _trials(case: dict) -> list[dict]:
    return [trial for trial in (case.get("trials") or []) if isinstance(trial, dict)]


def case_stability(case: dict) -> tuple[int, int, str, int]:
    """（通过轮次、有效轮次、判定、排除的基础设施轮次），与 eval_stability 同一口径。"""
    passed, total, excluded, verdict = eval_stability.classify_case(case)
    return passed, total, verdict, excluded


def _failed_checks(case: dict) -> list[str]:
    checks = set()
    for trial in _trials(case):
        if trial.get("passed"):
            continue
        checks.update(str(name) for name in (trial.get("failed_checks") or []))
    return sorted(checks)


def _envelope_meta(envelope: dict) -> dict:
    return {
        "model": envelope.get("model"),
        "code_revision": envelope.get("code_revision"),
        "prompt_sha256": envelope.get("prompt_sha256"),
        "dataset_sha256": envelope.get("dataset_sha256"),
        "repeat": envelope.get("repeat"),
    }


def compare_envelopes(baseline: dict, candidate: dict) -> dict:
    """按稳定性判定比较两份 envelope：稳定退化才算回归，单轮抖动只报 FLAKY。"""
    before = {str(case["key"]): case for case in baseline.get("cases") or []
              if isinstance(case, dict) and case.get("key") is not None}
    after = {str(case["key"]): case for case in candidate.get("cases") or []
             if isinstance(case, dict) and case.get("key") is not None}

    regressions: list[dict] = []
    unstable: list[dict] = []
    improvements: list[dict] = []
    infra_failures: list[dict] = []
    safety_failures: list[dict] = []

    for key, case in before.items():
        current = after.get(key)
        if current is None:
            continue
        base = case_stability(case)
        cur = case_stability(current)
        entry = {
            "key": key,
            "safety": bool(current.get("safety")),
            "baseline_passed": base[0],
            "baseline_total": base[1],
            "candidate_passed": cur[0],
            "candidate_total": cur[1],
            "excluded_infra": cur[3],
            "failed_checks": _failed_checks(current),
        }
        valid_trials = eval_stability.case_trials(current)[0]
        if cur[3]:
            # 有轮次被基础设施污染：本轮不可作基线证据，但已排除的轮次不参与稳定性判定。
            infra_failures.append(entry)
        if cur[1] == 0:
            # 所有轮次都被排除时没有可用证据，不能按“通过”或“波动”计。
            continue
        if entry["safety"] and any(not trial.get("passed") for trial in valid_trials):
            # 安全用例零容忍：有效轮次里任意一轮失败就拦。
            safety_failures.append(entry)
        if base[2] != "STABLE_PASS" and cur[2] == "STABLE_PASS":
            improvements.append(entry)
            continue
        if cur[2] == "STABLE_FAIL" and base[2] != "STABLE_FAIL":
            regressions.append(entry)
        elif cur[2] == "UNSTABLE" and base[2] == "STABLE_PASS":
            unstable.append(entry)

    removed = [{"key": key, "safety": bool(case.get("safety"))}
               for key, case in before.items() if key not in after]
    added = [{"key": key, "safety": bool(case.get("safety"))}
             for key, case in after.items() if key not in before]
    safety_missing = [item for item in removed if item["safety"]]

    baseline_passed = sum(1 for case in before.values()
                          if eval_stability.classify_case(case)[3] == "STABLE_PASS")
    candidate_passed = sum(1 for case in after.values()
                           if eval_stability.classify_case(case)[3] == "STABLE_PASS")

    if regressions or safety_failures or safety_missing:
        verdict = "REGRESSION"
    elif infra_failures:
        verdict = "INVALID_RUN"
    elif unstable:
        verdict = "FLAKY"
    else:
        verdict = "PASS"

    return {
        "baseline_passed": baseline_passed,
        "baseline_total": len(before),
        "candidate_passed": candidate_passed,
        "candidate_total": len(after),
        "regressions": regressions,
        "unstable": unstable,
        "improvements": improvements,
        "infra_failures": infra_failures,
        "safety_failures": safety_failures,
        "safety_missing": safety_missing,
        "removed": removed,
        "added": added,
        "verdict": verdict,
    }


def run_envelope_gate(candidate_dir: Path, baseline_root: Path) -> dict:
    """读 harness envelope 判定回归；四套件缺一即 NOT_RUN，不接受子集冒充全量。"""
    key = prompt_key()
    baseline_dir = baseline_root / key
    reports: list[dict] = []
    present: list[str] = []
    missing: list[str] = []
    for suite in ENVELOPE_SUITES:
        candidate = envelope_path(candidate_dir, suite)
        if not candidate.exists():
            missing.append(suite)
            continue
        present.append(suite)
        baseline = envelope_path(baseline_dir, suite)
        if not baseline.exists():
            raise ValueError(
                f"缺少当前 prompt 版本 {key} 的基线 envelope harness-{suite}.json；"
                "请先审阅候选报告并执行 --promote-baseline"
            )
        baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
        candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
        row = compare_envelopes(baseline_data, candidate_data)
        row["name"] = suite
        row["baseline"] = _envelope_meta(baseline_data)
        row["candidate"] = _envelope_meta(candidate_data)
        reports.append(row)
    if not reports:
        raise ValueError(f"候选目录 {candidate_dir} 没有可对比的 envelope")

    mismatches: list[dict] = []
    warnings: list[str] = []
    for row in reports:
        before, after = row["baseline"], row["candidate"]
        if (before.get("model") or None) != (after.get("model") or None):
            mismatches.append({"suite": row["name"], "field": "model",
                               "baseline": before.get("model"),
                               "candidate": after.get("model")})
        for field, label in (("code_revision", "代码版本"),
                             ("prompt_sha256", "提示词指纹"),
                             ("dataset_sha256", "题集指纹")):
            if (before.get(field) or None) != (after.get(field) or None):
                warnings.append(f"{row['name']} {label}不同：{before.get(field)} → "
                                f"{after.get(field)}；跨版本对比结论仍需人工确认")
        repeat = after.get("repeat")
        if isinstance(repeat, int) and repeat < MIN_STATISTICAL_TRIALS:
            warnings.append(f"{row['name']} 只采样 {repeat} 轮；"
                            f"少于 {MIN_STATISTICAL_TRIALS} 轮只能区分全过/全败，"
                            "不能据此给出统计显著性结论")

    if missing:
        verdict = "NOT_RUN"
    elif mismatches:
        # 跨模型对比不是实现回归证据；必须先在同一模型下重跑。
        verdict = "INVALID_RUN"
    elif any(row["verdict"] == "REGRESSION" for row in reports):
        verdict = "REGRESSION"
    elif any(row["verdict"] == "INVALID_RUN" for row in reports):
        verdict = "INVALID_RUN"
    elif any(row["verdict"] == "FLAKY" for row in reports):
        verdict = "FLAKY"
    else:
        verdict = "PASS"
    return {
        "mode": "envelope",
        "prompt_key": key,
        "baseline_dir": str(baseline_dir),
        "candidate_dir": str(candidate_dir),
        "reports": reports,
        "meta_mismatches": mismatches,
        "warnings": warnings,
        "coverage": {"present": present, "missing": missing,
                     "required": list(ENVELOPE_SUITES),
                     "note": "四份 harness envelope 必须全部重跑；缺少任一判定 NOT_RUN"},
        "verdict": verdict,
    }


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
    existing += [name for name in ENVELOPE_FILES if (target / name).exists()]
    if existing and not force:
        raise ValueError(f"当前 prompt 版本已有基线（{', '.join(existing)}）；覆盖需 --force")
    files = [name for name in REPORT_FILES.values() if (candidate_dir / name).exists()]
    envelopes = [name for name in ENVELOPE_FILES if (candidate_dir / name).exists()]
    if not files and not envelopes:
        raise ValueError(f"候选目录 {candidate_dir} 没有可登记报告")
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    previous: dict = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
    # 只登记 envelope 时保留既有原始报告：两套口径共存到迁移完成，不能把旧证据元数据抹掉。
    previous_files = [name for name in previous.get("files") or []
                      if (target / name).exists() and name not in files]
    previous_envelopes = [name for name in previous.get("envelopes") or []
                          if (target / name).exists() and name not in envelopes]
    registered = files + previous_files
    registered_envelopes = envelopes + previous_envelopes
    missing = [name for name in REPORT_FILES.values() if name not in registered]
    report_versions = {
        name: _report_versions(json.loads((candidate_dir / name).read_text(encoding="utf-8")))
        for name in files
    }
    envelope_meta = {
        name: _envelope_meta(json.loads((candidate_dir / name).read_text(encoding="utf-8")))
        for name in envelopes
    }
    current = {"routing": prompt_registry.prompt_version("routing"),
               "planner": prompt_registry.prompt_version("planner")}
    carried_forward = [
        {"file": name, "versions": {prompt: versions for prompt, versions in versions.items()
                                    if prompt in current and versions != [current[prompt]]}}
        for name, versions in report_versions.items()
    ]
    carried_forward = [item for item in carried_forward if item["versions"]]
    registered_versions = dict(previous.get("report_versions") or {})
    registered_versions.update(report_versions)
    registered_versions = {name: value for name, value in registered_versions.items()
                           if name in registered}
    registered_meta = dict(previous.get("envelope_meta") or {})
    registered_meta.update(envelope_meta)
    registered_meta = {name: registered_meta[name] for name in registered_envelopes
                       if name in registered_meta}
    carried = [item for item in (previous.get("carried_forward") or [])
               if item.get("file") in registered]
    carried += [item for item in carried_forward if item not in carried]
    for name in files + envelopes:
        shutil.copyfile(candidate_dir / name, target / name)
    manifest = {
        # 保留旧 manifest 的采集说明等扩展字段；只覆盖本次登记的元数据。
        **previous,
        "prompt_key": key,
        "routing_version": prompt_registry.prompt_version("routing"),
        "planner_version": prompt_registry.prompt_version("planner"),
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "files": registered,
        "envelopes": registered_envelopes,
        "envelope_meta": registered_meta,
        "coverage": {"files": registered, "missing": missing,
                     "note": "只登记候选目录实际存在的报告；未重跑项在 coverage.missing 中显式留痕"},
        "report_versions": registered_versions,
        "carried_forward": carried,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"prompt_key": key, "baseline_dir": str(target), "files": registered,
            "envelopes": registered_envelopes, "coverage": manifest["coverage"],
            "report_versions": registered_versions, "carried_forward": carried}


def _format_envelope_case(item: dict) -> str:
    parts = [f"{item['key']} {item['baseline_passed']}/{item['baseline_total']} → "
             f"{item['candidate_passed']}/{item['candidate_total']}"]
    if item.get("excluded_infra"):
        parts.append(f"排除基础设施 {item['excluded_infra']} 轮")
    if item.get("failed_checks"):
        parts.append("失败检查：" + "、".join(item["failed_checks"]))
    return "；".join(parts)


def render_envelope_text(result: dict) -> str:
    lines = [f"prompt 版本：{result['prompt_key']}", f"基线目录：{result['baseline_dir']}",
             f"候选目录：{result['candidate_dir']}"]
    for row in result["reports"]:
        lines.append(f"- {row['name']}：{row['baseline_passed']}/{row['baseline_total']} → "
                     f"{row['candidate_passed']}/{row['candidate_total']}，{row['verdict']}")
        for label, key in (("稳定回归", "regressions"), ("不稳定（多轮波动）", "unstable"),
                           ("基础设施失败", "infra_failures"), ("安全失败", "safety_failures"),
                           ("改善", "improvements")):
            rows = row.get(key) or []
            if rows:
                lines.append(f"  {label}：" + "、".join(
                    _format_envelope_case(item) for item in rows))
        if row["removed"]:
            lines.append("  缺失用例：" + "、".join(item["key"] for item in row["removed"]))
        if row["added"]:
            lines.append("  新增用例：" + "、".join(item["key"] for item in row["added"]))
    lines.append(f"判定：{result['verdict']}")
    verdict_notes = {
        "INVALID_RUN": "（基础设施失败或跨模型对比，本轮不可作基线证据，需重跑取证）",
        "NOT_RUN": "（缺少套件 envelope，按子集不能判通过）",
        "FLAKY": "（存在多轮波动用例，非稳定回归；需补足轮次后重新判定）",
    }
    if result["verdict"] in verdict_notes:
        lines.append("说明：" + verdict_notes[result["verdict"]])
    for item in result.get("meta_mismatches") or []:
        lines.append(f"阻断：{item['suite']} 模型不一致 {item['baseline']} → {item['candidate']}；"
                     "跨模型对比不能判回归")
    coverage = result.get("coverage") or {}
    if coverage.get("missing"):
        lines.append("覆盖度：缺少 " + "、".join(coverage["missing"]) + "（未判定 PASS）")
    for warning in result.get("warnings") or []:
        lines.append(f"注意：{warning}")
    return "\n".join(lines)


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
    parser.add_argument("--candidate-dir", type=Path, default=None,
                        help="候选目录；默认 reports 模式为 docs/evaluation/candidate，"
                             "envelope 模式为其下 envelopes/")
    parser.add_argument("--baseline-root", type=Path,
                        default=ROOT / "docs/evaluation/baselines", help="基线根目录")
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="存在回归、安全失败或覆盖度不足（NOT_RUN）时返回 2")
    parser.add_argument("--mode", choices=("reports", "envelope"), default="reports",
                        help="reports：读原始评测报告；envelope：直连 eval_harness 输出")
    parser.add_argument("--promote-baseline", action="store_true",
                        help="把候选报告登记为当前 prompt 版本基线")
    parser.add_argument("--force", action="store_true", help="覆盖已有基线")
    parser.add_argument("--retest-attempts", type=int, default=0,
                        help="对回归用例按编号重跑 N 次（≥3）复核是否为采样波动")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    if args.candidate_dir is None:
        args.candidate_dir = ROOT / "docs/evaluation/candidate"
        if args.mode == "envelope":
            # envelope 与原始报告分开存放，避免门禁读到同一目录里的旧报告。
            args.candidate_dir = args.candidate_dir / "envelopes"

    try:
        if args.promote_baseline:
            result = promote_baseline(args.candidate_dir, args.baseline_root, force=args.force)
            print(json.dumps(result, ensure_ascii=False) if args.json else
                  f"已登记基线：{result['baseline_dir']}（{', '.join(result['files'] + result['envelopes']) or '—'}）")
            if not args.json:
                for item in result["carried_forward"]:
                    detail = "、".join(f"{name}={','.join(versions)}"
                                       for name, versions in item["versions"].items())
                    print(f"注意：{item['file']} 延用旧版本报告（{detail}），需在报告中保留说明")
            return 0
        if args.mode == "envelope":
            if args.retest_attempts:
                raise ValueError("envelope 模式已按多轮采样复核；不要再用 --retest-attempts")
            result = run_envelope_gate(args.candidate_dir, args.baseline_root)
        else:
            result = run_gate(args.candidate_dir, args.baseline_root)
            if args.retest_attempts and result["verdict"] == "REGRESSION":
                result = retest_regressions(args.candidate_dir, result,
                                            attempts=args.retest_attempts)
    except (OSError, ValueError) as exc:
        print(f"评测门禁失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.mode == "envelope":
        print(render_envelope_text(result))
    else:
        print(render_text(result))
    if args.fail_on_regression and result["verdict"] in {"REGRESSION", "NOT_RUN", "INVALID_RUN"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())