"""按月汇总评测结果，回答“这个月比上个月稳了还是退步”。

数据来自 `record_eval_run.py` 写入的 ai_eval_runs / ai_eval_case_results；只读，
不发起模型调用。稳定通过率口径为 STABLE_PASS / 用例总数，与 eval_stability 一致。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai.model import AIEvalRun  # noqa: E402

SUITES = ("routing", "tasks", "business", "prod")


def month_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m")


def summarize(runs: list, *, months: int = 6) -> list[dict]:
    """按自然月聚合；同一月多次运行累加，稳定通过率按用例数加权。"""
    buckets: dict[str, dict] = {}
    for run in runs:
        key = month_key(run.collected_at)
        bucket = buckets.setdefault(key, {
            "month": key, "runs": 0, "cases": 0, "stable_pass": 0, "unstable": 0,
            "stable_fail": 0, "no_evidence": 0, "excluded_infra": 0, "verdicts": {},
        })
        bucket["runs"] += 1
        bucket["cases"] += run.cases_total
        bucket["stable_pass"] += run.stable_pass
        bucket["unstable"] += run.unstable
        bucket["stable_fail"] += run.stable_fail
        bucket["no_evidence"] += run.no_evidence
        bucket["excluded_infra"] += run.excluded_infra
        bucket["verdicts"][run.verdict] = bucket["verdicts"].get(run.verdict, 0) + 1
    rows = sorted(buckets.values(), key=lambda item: item["month"], reverse=True)
    rows = rows[:months]
    for row in rows:
        row["stable_rate"] = (row["stable_pass"] / row["cases"]) if row["cases"] else 0.0
    return rows


def load_runs(db, *, suite: str = "") -> list:
    query = select(AIEvalRun).order_by(AIEvalRun.collected_at)
    if suite:
        query = query.where(AIEvalRun.suite == suite)
    return list(db.scalars(query).all())


def render_markdown(rows: list[dict], *, suite: str = "") -> str:
    scope = f"（{suite}）" if suite else ""
    lines = [f"# 评测月度趋势{scope}", "",
             "| 月份 | 运行次数 | 用例数 | STABLE_PASS | UNSTABLE | STABLE_FAIL | 排除基础设施轮次 | 稳定通过率 | 判定分布 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in rows:
        verdicts = "、".join(f"{name}={count}" for name, count in sorted(row["verdicts"].items()))
        lines.append(f"| {row['month']} | {row['runs']} | {row['cases']} | {row['stable_pass']} | "
                     f"{row['unstable']} | {row['stable_fail']} | {row['excluded_infra']} | "
                     f"{row['stable_rate']:.1%} | {verdicts or '—'} |")
    if not rows:
        lines.append("| — | 0 | 0 | 0 | 0 | 0 | 0 | 未测 | — |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--months", type=int, default=6, help="保留最近 N 个月")
    parser.add_argument("--suite", choices=SUITES, default="", help="只看单个套件")
    parser.add_argument("--out", type=Path, help="Markdown 输出路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)
    if args.months < 1:
        parser.error("--months 必须为正数")
    try:
        with SessionLocal() as db:
            rows = summarize(load_runs(db, suite=args.suite), months=args.months)
    except OSError as exc:  # 数据库不可用
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    text = render_markdown(rows, suite=args.suite)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())