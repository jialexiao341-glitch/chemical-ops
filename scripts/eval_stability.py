"""按 Wilson 区间判定用例稳定性，替代“单次失败即回归”。

读取 eval_harness 生成的 envelope；每个用例按 trials 计算通过率与 95% 下界：
    下界 >= 0.7  → STABLE_PASS
    上界 <= 0.3  → STABLE_FAIL
    其余          → UNSTABLE（采样波动，交人工队列，不计回归）
失败轮次若错误类别全部属于基础设施（TRANSIENT_INFRA / AMBIGUOUS_TIMEOUT），
该轮不计入统计，另记 `excluded_infra`；全部轮次都被排除时判 NO_EVIDENCE，
不能用 0 轮冒充通过。
退出码：0 无 UNSTABLE / NO_EVIDENCE；2 存在 UNSTABLE 或 NO_EVIDENCE。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

STABLE_PASS_FLOOR = 0.7
STABLE_FAIL_CEILING = 0.3
NO_EVIDENCE = "NO_EVIDENCE"

# 只读合成评测中的通信抖动与结果未知超时统一不计为实现退化，由外层重跑或判 INVALID_RUN。
INFRA_ERROR_CLASSES = {"TRANSIENT_INFRA", "AMBIGUOUS_TIMEOUT"}


def is_infra_classes(classes: object) -> bool:
    """判断错误类别集合是否全部属于可隔离的基础设施/响应超时故障。"""
    normalized = {str(item) for item in (classes or ()) if item}
    return bool(normalized) and normalized <= INFRA_ERROR_CLASSES


def extract_error_classes(row: dict) -> set[str]:
    """收集用例行及各轮 run_meta.error.class，统一供 harness、报告比对与断点筛选使用。"""
    classes: set[str] = set()
    sources = [row.get("run_meta") or {}]
    sources += [(round_data.get("run_meta") or {}) for round_data in (row.get("rounds") or [])
                if isinstance(round_data, dict)]
    for meta in sources:
        error = meta.get("error")
        if isinstance(error, dict) and error.get("class"):
            classes.add(str(error["class"]))
    return classes


def wilson(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 置信区间，小样本下比正态近似可靠。"""
    if total <= 0:
        return 0.0, 1.0
    rate = passed / total
    denominator = 1 + z * z / total
    centre = rate + z * z / (2 * total)
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)


def classify(passed: int, total: int) -> str:
    if total <= 0:
        return NO_EVIDENCE
    if total < 5:
        # 轮次少时 Wilson 下界过保守（3/3 仅约 0.44），按全通过/全失败直接判定。
        if passed == total:
            return "STABLE_PASS"
        if passed == 0:
            return "STABLE_FAIL"
        return "UNSTABLE"
    low, high = wilson(passed, total)
    if low >= STABLE_PASS_FLOOR:
        return "STABLE_PASS"
    if high <= STABLE_FAIL_CEILING:
        return "STABLE_FAIL"
    return "UNSTABLE"


def trial_infra(trial: dict) -> bool:
    """失败轮次且错误类别全部属于基础设施：本轮不可作为能力证据。"""
    if trial.get("passed"):
        return False
    return is_infra_classes(trial.get("error_classes") or [])


def case_trials(case: dict) -> tuple[list[dict], int]:
    """返回（有效轮次，被排除的基础设施轮次）。门禁与稳定性报告共用这一口径。"""
    trials = [trial for trial in (case.get("trials") or []) if isinstance(trial, dict)]
    valid = [trial for trial in trials if not trial_infra(trial)]
    return valid, len(trials) - len(valid)


def classify_case(case: dict) -> tuple[int, int, int, str]:
    """（通过轮次，有效轮次，排除轮次，判定）。"""
    valid, excluded = case_trials(case)
    passed = sum(1 for trial in valid if trial.get("passed"))
    return passed, len(valid), excluded, classify(passed, len(valid))


def summarize(envelope: dict) -> list[dict]:
    rows = []
    for entry in envelope.get("cases") or []:
        passed, total, excluded, verdict = classify_case(entry)
        low, high = wilson(passed, total)
        rows.append({
            "key": entry["key"],
            "runs": total,
            "passed": passed,
            "excluded_infra": excluded,
            "rate": passed / total if total else 0.0,
            "wilson_low": round(low, 3),
            "wilson_high": round(high, 3),
            "verdict": verdict,
        })
    return rows


def render_markdown(rows: list[dict], suite: str) -> str:
    unstable = [row for row in rows if row["verdict"] == "UNSTABLE"]
    no_evidence = [row for row in rows if row["verdict"] == NO_EVIDENCE]
    lines = [f"# 稳定性评估：{suite}（{len(rows)} 条用例）", "",
             "| 用例 | 有效轮次 | 通过 | 排除的基础设施轮次 | 通过率 | Wilson 95% | 判定 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        name = row["key"] if len(row["key"]) <= 40 else row["key"][:37] + "…"
        lines.append(f"| {name} | {row['runs']} | {row['passed']} | {row['excluded_infra']} | "
                     f"{row['rate']:.0%} | [{row['wilson_low']}, {row['wilson_high']}] | "
                     f"{row['verdict']} |")
    lines += ["", f"不稳定用例 {len(unstable)} 条"
                  + ("：" + "、".join(row["key"] for row in unstable) if unstable else "")]
    lines.append(f"无有效轮次用例 {len(no_evidence)} 条"
                 + ("：" + "、".join(row["key"] for row in no_evidence) if no_evidence else ""))
    excluded = sum(row["excluded_infra"] for row in rows)
    if excluded:
        lines.append(f"被排除的基础设施失败轮次 {excluded} 轮；这些轮次不参与稳定性判定，"
                     "但说明该批次存在模型服务抖动，仍需重跑取证")
    return "\n".join(lines)


def load_envelopes(paths: list[Path]) -> dict:
    """多份 envelope 合并成一个；同一 key 的 trials 累加，便于跨批次统计。"""
    merged: dict[str, dict] = {}
    meta: dict = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for name in ("model", "code_revision", "dataset_sha256", "prompt_sha256"):
            if data.get(name) and not meta.get(name):
                meta[name] = data[name]
        for entry in data.get("cases") or []:
            target = merged.setdefault(entry["key"], {"key": entry["key"], "trials": []})
            target["trials"].extend(entry.get("trials") or [])
    return {"cases": list(merged.values()), **meta}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--envelope", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, help="Markdown 报告输出路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 明细")
    args = parser.parse_args(argv)
    try:
        envelope = load_envelopes(args.envelope)
    except (OSError, ValueError) as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1
    rows = summarize(envelope)
    suite = envelope.get("suite") or "mixed"
    text = render_markdown(rows, suite)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else text)
    return 2 if any(row["verdict"] in {"UNSTABLE", NO_EVIDENCE} for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())