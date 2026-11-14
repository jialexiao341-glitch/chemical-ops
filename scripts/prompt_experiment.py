"""Prompt 变体对照实验：同一题集上的配对差异与 McNemar 精确检验。

只读两份 envelope（基线变体、候选变体），输出逐用例列联表、改善/退化清单与 p 值；
不写基线、不提供 promote 入口，符合“候选可生成、基线不可自动写”的红线。
基础设施失败轮次沿用 eval_stability 的口径排除，不当作能力差异。
"""
from __future__ import annotations

import argparse
import json
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import eval_stability  # noqa: E402

SUITES = ("routing", "tasks", "business", "prod")
ALPHA = 0.05
VERDICTS = ("IMPROVED", "DEGRADED", "INCONCLUSIVE", "NO_EVIDENCE", "INVALID")


def load_envelope_dir(directory: Path) -> dict[str, dict]:
    """读取目录下 harness-<suite>.json；缺哪套件就跳过哪套件，由调用方决定是否可比。"""
    envelopes: dict[str, dict] = {}
    for suite in SUITES:
        path = directory / f"harness-{suite}.json"
        if not path.exists():
            continue
        envelopes[suite] = json.loads(path.read_text(encoding="utf-8"))
    if not envelopes:
        raise ValueError(f"目录 {directory} 没有 harness-<suite>.json")
    return envelopes


def case_binary(case: dict) -> tuple[bool, int, int, int] | None:
    """（是否多数轮通过，通过轮次，有效轮次，排除轮次）；无有效轮次返回 None。"""
    passed, total, excluded, _ = eval_stability.classify_case(case)
    if total <= 0:
        return None
    return passed * 2 > total, passed, total, excluded


def mcnemar_exact(b: int, c: int) -> float:
    """McNemar 精确检验：不一致对按二项分布 0.5 做双侧检验。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, index) for index in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def classify_pair(b: int, c: int, p: float) -> str:
    """不一致对为零时是“无差异”，不是“无证据”。"""
    if p < ALPHA and c > b:
        return "IMPROVED"
    if p < ALPHA and b > c:
        return "DEGRADED"
    return "INCONCLUSIVE"


def _case_rows(baseline: dict, candidate: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """按用例配对两份 envelope；返回（可比较、改善、退化、无证据）。"""
    before = {str(case["key"]): case for case in baseline.get("cases") or []
              if isinstance(case, dict) and case.get("key") is not None}
    after = {str(case["key"]): case for case in candidate.get("cases") or []
             if isinstance(case, dict) and case.get("key") is not None}
    rows, excluded = [], []
    for key, case in before.items():
        current = after.get(key)
        if current is None:
            continue
        left, right = case_binary(case), case_binary(current)
        if left is None or right is None:
            excluded.append({"key": key, "reason": "无有效轮次"})
            continue
        rows.append({
            "key": key,
            "baseline_passed": left[1],
            "baseline_total": left[2],
            "baseline_infra": left[3],
            "candidate_passed": right[1],
            "candidate_total": right[2],
            "candidate_infra": right[3],
            "baseline_ok": left[0],
            "candidate_ok": right[0],
        })
    improved = [row for row in rows if not row["baseline_ok"] and row["candidate_ok"]]
    degraded = [row for row in rows if row["baseline_ok"] and not row["candidate_ok"]]
    return rows, improved, degraded, excluded


def compare_suite(baseline: dict, candidate: dict) -> dict:
    """单套件配对比较：2×2 表、McNemar p、改善/退化清单。"""
    rows, improved, degraded, excluded = _case_rows(baseline, candidate)
    both_pass = sum(1 for row in rows if row["baseline_ok"] and row["candidate_ok"])
    both_fail = sum(1 for row in rows if not row["baseline_ok"] and not row["candidate_ok"])
    baseline_only = len(degraded)
    candidate_only = len(improved)
    p = mcnemar_exact(baseline_only, candidate_only)
    compared = len(rows)
    return {
        "suite": baseline.get("suite"),
        "cases": compared,
        "both_pass": both_pass,
        "baseline_only": baseline_only,
        "candidate_only": candidate_only,
        "both_fail": both_fail,
        "excluded": excluded,
        "delta": (candidate_only - baseline_only) / compared if compared else 0.0,
        "mcnemar_p": p,
        "verdict": classify_pair(baseline_only, candidate_only, p) if compared else "NO_EVIDENCE",
        "improved": improved,
        "degraded": degraded,
    }


def run(baseline_dir: Path, candidate_dir: Path, suites: tuple[str, ...] = ()) -> dict:
    """比较两个变体的 envelope 目录；只出结论，不写基线。"""
    baseline = load_envelope_dir(baseline_dir)
    candidate = load_envelope_dir(candidate_dir)
    selected = suites or tuple(suite for suite in SUITES
                               if suite in baseline and suite in candidate)
    if not selected:
        raise ValueError("两个目录没有可比对的共同套件")
    missing = [suite for suite in selected if suite not in baseline or suite not in candidate]
    if missing:
        raise ValueError(f"缺少套件 envelope：{', '.join(missing)}")
    baseline_meta = {suite: baseline[suite].get("model") for suite in selected}
    candidate_meta = {suite: candidate[suite].get("model") for suite in selected}
    mismatch = [suite for suite in selected if baseline_meta[suite] != candidate_meta[suite]]
    rows = []
    for suite in selected:
        row = compare_suite(baseline[suite], candidate[suite])
        row["model_mismatch"] = baseline_meta[suite] != candidate_meta[suite]
        rows.append(row)
    verdict = "INVALID" if mismatch else _overall_verdict(rows)
    warnings = []
    if mismatch:
        warnings.append("跨模型对比：%s 的模型不同，结论不可作为变体证据，需同模型重跑" % "、".join(mismatch))
    for suite in selected:
        if baseline[suite].get("dataset_sha256") != candidate[suite].get("dataset_sha256"):
            warnings.append(f"{suite} 题集指纹不同；用例差异已按 key 剔除，仍需人工确认")
    return {
        "baseline_dir": str(baseline_dir),
        "candidate_dir": str(candidate_dir),
        "suites": rows,
        "model_mismatch": mismatch,
        "warnings": warnings,
        "verdict": verdict,
    }


def _overall_verdict(rows: list[dict]) -> str:
    verdicts = [row["verdict"] for row in rows]
    if "DEGRADED" in verdicts:
        return "DEGRADED"
    if "IMPROVED" in verdicts:
        return "IMPROVED"
    if all(verdict == "NO_EVIDENCE" for verdict in verdicts):
        return "NO_EVIDENCE"
    return "INCONCLUSIVE"


def render_text(result: dict) -> str:
    lines = ["# Prompt 变体实验", "",
             f"基线：{result['baseline_dir']}", f"候选：{result['candidate_dir']}", "",
             "| 套件 | 用例 | baseline 通过 | candidate 通过 | 改善 | 退化 | 差值 | McNemar p | 判定 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in result["suites"]:
        lines.append(f"| {row['suite']} | {row['cases']} | {row['both_pass'] + row['baseline_only']} | "
                     f"{row['both_pass'] + row['candidate_only']} | {row['candidate_only']} | "
                     f"{row['baseline_only']} | {row['delta']:+.0%} | {row['mcnemar_p']:.4f} | "
                     f"{row['verdict']} |")
    lines += ["", f"结论：{result['verdict']}"]
    for warning in result["warnings"]:
        lines.append(f"注意：{warning}")
    for row in result["suites"]:
        if row["improved"]:
            lines.append(f"{row['suite']} 改善：" + "、".join(item["key"] for item in row["improved"]))
        if row["degraded"]:
            lines.append(f"{row['suite']} 退化：" + "、".join(item["key"] for item in row["degraded"]))
        if row["excluded"]:
            lines.append(f"{row['suite']} 无有效轮次：" + "、".join(item["key"] for item in row["excluded"]))
    lines += ["", "口径：每条用例取有效轮次（排除 TRANSIENT_INFRA / AMBIGUOUS_TIMEOUT）的多数结果作为配对二值，"
                  "McNemar 精确检验按不一致对做双侧二项检验；`p<0.05` 才判改善或退化。",
              "本脚本只读 envelope，不写基线；基线变更仍走人工 `eval_prompt_gate.py --promote-baseline`。"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, required=True,
                        help="基线变体的 envelope 目录（含 harness-<suite>.json）")
    parser.add_argument("--candidate-dir", type=Path, required=True,
                        help="候选变体的 envelope 目录")
    parser.add_argument("--suite", action="append", choices=SUITES, default=[],
                        help="只比较指定套件，可重复；默认比较两目录共有的套件")
    parser.add_argument("--out", type=Path, help="Markdown 报告输出路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    try:
        result = run(args.baseline_dir, args.candidate_dir, tuple(args.suite))
    except (OSError, ValueError) as exc:
        print(f"实验失败：{exc}", file=sys.stderr)
        return 1
    text = render_text(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else text)
    return 2 if result["verdict"] == "INVALID" else 0


if __name__ == "__main__":
    raise SystemExit(main())