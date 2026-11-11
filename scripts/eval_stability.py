"""按 Wilson 区间判定用例稳定性，替代“单次失败即回归”。

读取 eval_harness 生成的 envelope；每个用例按 trials 计算通过率与 95% 下界：
    下界 >= 0.7  → STABLE_PASS
    上界 <= 0.3  → STABLE_FAIL
    其余          → UNSTABLE（采样波动，交人工队列，不计回归）
退出码：0 无 UNSTABLE；2 存在 UNSTABLE。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

STABLE_PASS_FLOOR = 0.7
STABLE_FAIL_CEILING = 0.3


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


def summarize(envelope: dict) -> list[dict]:
    rows = []
    for entry in envelope.get("cases") or []:
        trials = entry.get("trials") or []
        total = len(trials)
        passed = sum(1 for trial in trials if trial.get("passed"))
        low, high = wilson(passed, total)
        rows.append({
            "key": entry["key"],
            "runs": total,
            "passed": passed,
            "rate": passed / total if total else 0.0,
            "wilson_low": round(low, 3),
            "wilson_high": round(high, 3),
            "verdict": classify(passed, total),
        })
    return rows


def render_markdown(rows: list[dict], suite: str) -> str:
    unstable = [row for row in rows if row["verdict"] == "UNSTABLE"]
    lines = [f"# 稳定性评估：{suite}（{len(rows)} 条用例）", "",
             "| 用例 | 轮次 | 通过 | 通过率 | Wilson 95% | 判定 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        name = row["key"] if len(row["key"]) <= 40 else row["key"][:37] + "…"
        lines.append(f"| {name} | {row['runs']} | {row['passed']} | {row['rate']:.0%} | "
                     f"[{row['wilson_low']}, {row['wilson_high']}] | {row['verdict']} |")
    lines += ["", f"不稳定用例 {len(unstable)} 条"
                  + ("：" + "、".join(row["key"] for row in unstable) if unstable else "")]
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
    return 2 if any(row["verdict"] == "UNSTABLE" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())