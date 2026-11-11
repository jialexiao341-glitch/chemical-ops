"""对比两份评测报告：总通过率变化、逐用例 PASS→FAIL / FAIL→PASS 与安全回归。

支持 evaluate_intent_routing.py、evaluate_agent_tasks.py、evaluate_agent_business.py
生成的 JSON 证据；只读取本地文件，不发起任何网络请求，也不改写历史报告。
同一条用例有多次轮次或重复运行时，全部通过才算该用例通过。

退出码：0 通过；1 输入或格式错误；2 存在回归、安全失败或基础设施失败
（需配合 --fail-on-regression，否则只报告不拦截）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

KIND_NAMES = {
    "intent_routing": "路由评测",
    "agent_tasks": "Agent 任务评测",
    "agent_business": "业务场景评测",
    "summary": "汇总报告",
}

META_KEYS = ("dataset_version", "dataset_sha256", "model", "code_revision")

# 模型服务限流、连接中断等基础设施失败不代表实现退化；单列后由门禁判 INVALID_RUN。
INFRA_ERROR_CLASSES = {"TRANSIENT_INFRA"}


def _error_classes(row: dict) -> set[str]:
    """收集用例行及其各轮的 error.class，用于区分实现回归与基础设施故障。"""
    classes: set[str] = set()
    sources = [row.get("run_meta") or {}]
    sources += [(round_data.get("run_meta") or {}) for round_data in (row.get("rounds") or [])
                if isinstance(round_data, dict)]
    for meta in sources:
        error = meta.get("error")
        if isinstance(error, dict) and error.get("class"):
            classes.add(str(error["class"]))
    return classes


def _infra_failed(row: dict) -> bool:
    """失败但错误类别全部属于基础设施时，不参与回归与安全失败判定。"""
    if row.get("passed"):
        return False
    classes = _error_classes(row)
    return bool(classes) and classes <= INFRA_ERROR_CLASSES


def load_report(path: Path) -> dict:
    """读取并校验报告 JSON；结构错误在调用方统一转成退出码 1。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象")
    return data


def detect_kind(report: dict) -> str:
    """按用例字段识别报告来源，避免依赖文件名或写入方自报格式。"""
    cases = report.get("cases")
    rows = [row for row in cases if isinstance(row, dict)] if isinstance(cases, list) else []
    if rows:
        if any("trial" in row for row in rows):
            return "agent_business"
        if any("id" in row for row in rows):
            return "agent_tasks"
        if any("question" in row for row in rows):
            return "intent_routing"
    total, passed = report.get("total"), report.get("passed")
    if isinstance(total, int) and isinstance(passed, int):
        return "summary"
    raise ValueError("无法识别的评测报告结构；需要 cases 用例列表或 total/passed 汇总字段")


def _new_entry(key: str, label: str, safety: bool) -> dict:
    return {
        "key": key,
        "label": label,
        "safety": safety,
        "runs": 0,
        "passed_runs": 0,
        "failed_runs": [],
        "failed_checks": [],
        "infra_failed_runs": 0,
    }


def _case_key_and_label(row: dict, kind: str) -> tuple[str, str, bool]:
    if kind == "intent_routing":
        question = str(row.get("question"))
        return question, question, False
    case_id = str(row.get("id"))
    return case_id, case_id, bool(row.get("safety"))


def normalize(report: dict) -> dict:
    """把三种报告结构归一成“用例 → 是否全部通过”，并保留失败检查名。"""
    kind = detect_kind(report)
    if kind == "summary":
        total, passed = int(report["total"]), int(report["passed"])
        return {
            "kind": kind,
            **{key: report.get(key) for key in META_KEYS},
            "cases": [],
            "total": total,
            "passed": passed,
            "pass_rate": passed / total if total else None,
        }

    entries: dict[str, dict] = {}
    for row in report["cases"]:
        if not isinstance(row, dict):
            raise ValueError("cases 中存在非对象用例")
        key, label, safety = _case_key_and_label(row, kind)
        entry = entries.setdefault(key, _new_entry(key, label, safety))
        entry["safety"] = entry["safety"] or safety
        entry["runs"] += 1
        if row.get("passed"):
            entry["passed_runs"] += 1
            continue
        run_no = row.get("trial", row.get("round"))
        entry["failed_runs"].append(run_no)
        if _infra_failed(row):
            entry["infra_failed_runs"] += 1
        checks = row.get("checks") or {}
        for name, value in checks.items():
            if value is False and name not in entry["failed_checks"]:
                entry["failed_checks"].append(name)

    cases = list(entries.values())
    for entry in cases:
        entry["passed"] = entry["runs"] > 0 and entry["passed_runs"] == entry["runs"]
        entry["infra_failure"] = (not entry["passed"]) and entry["infra_failed_runs"] > 0
        entry["failed_checks"].sort()
        entry["failed_runs"] = [run for run in entry["failed_runs"] if run is not None]
    total = len(cases)
    passed = sum(1 for entry in cases if entry["passed"])
    return {
        "kind": kind,
        **{key: report.get(key) for key in META_KEYS},
        "cases": cases,
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else None,
    }


def _case_ref(entry: dict) -> dict:
    return {
        "key": entry["key"],
        "label": entry["label"],
        "safety": entry["safety"],
        "failed_checks": list(entry["failed_checks"]),
    }


def _short(value) -> str:
    if value is None:
        return "—"
    text = str(value)
    return text if len(text) <= 12 else text[:12] + "…"


def compare(baseline_report: dict, candidate_report: dict) -> dict:
    """比较两份报告；回归与安全失败分开列出，避免被总通过率抵消。"""
    baseline = normalize(baseline_report)
    candidate = normalize(candidate_report)
    baseline_by_key = {entry["key"]: entry for entry in baseline["cases"]}
    candidate_by_key = {entry["key"]: entry for entry in candidate["cases"]}

    regressions: list[dict] = []
    improvements: list[dict] = []
    infra_failures: list[dict] = []
    for key, before in baseline_by_key.items():
        after = candidate_by_key.get(key)
        if after is None:
            continue
        if before["passed"] and not after["passed"]:
            # 模型服务限流或断连造成的失败不是实现退化；由下面的 infra_failures 统一列出。
            if not after.get("infra_failure"):
                regressions.append({**_case_ref(after), "failed_runs": list(after["failed_runs"])})
        elif not before["passed"] and after["passed"]:
            improvements.append(_case_ref(after))

    removed = [_case_ref(entry) for key, entry in baseline_by_key.items() if key not in candidate_by_key]
    infra_failures = [
        {**_case_ref(entry), "failed_runs": list(entry["failed_runs"])}
        for entry in candidate["cases"] if entry.get("infra_failure")
    ]
    added = [_case_ref(entry) for key, entry in candidate_by_key.items() if key not in baseline_by_key]
    safety_failures = [
        _case_ref(entry) for entry in candidate["cases"]
        if entry["safety"] and not entry["passed"] and not entry.get("infra_failure")
    ]
    safety_missing = [
        _case_ref(entry)
        for key, entry in baseline_by_key.items()
        if entry["safety"] and key not in candidate_by_key
    ]

    rate = None
    if baseline["pass_rate"] is not None and candidate["pass_rate"] is not None:
        rate = (candidate["pass_rate"] - baseline["pass_rate"]) * 100

    blocked = bool(regressions or safety_failures or safety_missing)
    if blocked:
        verdict = "REGRESSION"
    elif infra_failures:
        # 有实现层之外的失败时整轮不可作为基线证据，但也不等于代码退化。
        verdict = "INVALID_RUN"
    else:
        verdict = "PASS"
    warnings = []
    labels = {
        "dataset_version": "题集版本",
        "dataset_sha256": "题集指纹",
        "model": "模型",
        "code_revision": "代码版本",
    }
    for key, label in labels.items():
        before, after = baseline.get(key), candidate.get(key)
        if before is None and after is None:
            continue
        if before == after:
            continue
        if key != "dataset_version":
            before = _short(before)
            after = _short(after)
        warnings.append(f"{label}不同：{before} → {after}；跨题集或跨版本的对比结论仍需人工确认")

    return {
        "baseline": baseline,
        "candidate": candidate,
        "pass_rate_delta_points": rate,
        "regressions": regressions,
        "improvements": improvements,
        "infra_failures": infra_failures,
        "safety_failures": safety_failures,
        "safety_missing": safety_missing,
        "removed": removed,
        "added": added,
        "warnings": warnings,
        "verdict": verdict,
    }


def _format_rate(rate: float | None) -> str:
    return "未测" if rate is None else f"{rate:.2%}"


def _format_delta(delta: float | None) -> str:
    if delta is None:
        return "无法比较（分母为 0）"
    return f"{delta:+.2f} 个百分点"


def _format_case(case: dict) -> str:
    parts = [case["label"]]
    if case["safety"]:
        parts.append("安全用例")
    if case.get("failed_checks"):
        parts.append("失败检查：" + "、".join(case["failed_checks"]))
    if case.get("failed_runs"):
        parts.append("失败轮次：" + "、".join(str(run) for run in case["failed_runs"]))
    return "；".join(parts)


def render_text(result: dict) -> str:
    """生成人读摘要：先给总量，再逐条列出退化与安全失败。"""
    baseline, candidate = result["baseline"], result["candidate"]
    lines = [
        f"评测对比：{KIND_NAMES[baseline['kind']]} → {KIND_NAMES[candidate['kind']]}",
        f"基线：{baseline['passed']}/{baseline['total']}（{_format_rate(baseline['pass_rate'])}）",
        f"候选：{candidate['passed']}/{candidate['total']}（{_format_rate(candidate['pass_rate'])}）",
        f"通过率变化：{_format_delta(result['pass_rate_delta_points'])}",
        "",
    ]
    for label, rows in (("回归（PASS→FAIL）", result["regressions"]),
                        ("基础设施失败（不计回归）", result.get("infra_failures", [])),
                        ("改善（FAIL→PASS）", result["improvements"]),
                        ("安全失败", result["safety_failures"]),
                        ("缺失的安全用例", result["safety_missing"])):
        lines.append(f"{label} {len(rows)} 条" + ("：" if rows else ""))
        lines.extend(f"  - {_format_case(row)}" for row in rows)
    lines.append("")
    lines.append(f"新增用例 {len(result['added'])} 条；缺失用例 {len(result['removed'])} 条")
    for warning in result["warnings"]:
        lines.append(f"注意：{warning}")
    lines.append("")
    verdict_notes = {
        "REGRESSION": "（存在回归或安全失败；--fail-on-regression 返回 2）",
        "INVALID_RUN": "（存在基础设施失败，本轮不可作基线证据；需重跑）",
    }
    lines.append("判定：" + result["verdict"] + verdict_notes.get(result["verdict"], ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, required=True, help="基线报告 JSON")
    parser.add_argument("--candidate", type=Path, required=True, help="候选报告 JSON")
    parser.add_argument(
        "--fail-on-regression", action="store_true",
        help="存在 PASS→FAIL 回归或安全失败时返回非 0",
    )
    parser.add_argument("--output", type=Path, help="可选：把对比结果另存为 JSON")
    args = parser.parse_args(argv)

    try:
        result = compare(load_report(args.baseline), load_report(args.candidate))
    except (OSError, ValueError) as exc:
        print(f"对比失败：{exc}", file=sys.stderr)
        return 1

    print(render_text(result))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_on_regression and result["verdict"] in {"REGRESSION", "INVALID_RUN"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
