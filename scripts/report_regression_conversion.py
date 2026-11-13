"""统计生产环境的差评/失败任务 -> 已批准回归用例转化时长；无数据时明确报空。

口径：
- 起点：同一任务的最早 `ai_feedback.rating='DOWN'` 时间；没有差评时回退任务创建时间。
- 终点：`ai_regression_cases.reviewed_at`（管理员批准时间）。
- 只统计 `status='APPROVED'`、带 `source_task_id` 且已审阅的记录。
- 默认排除 `SYN-` 开头的合成任务，避免 fixture 污染生产结论。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai_agent.error_policy import ErrorClass, classify  # noqa: E402
from app.modules.ai_agent.model import AIAgentTask, AIFeedback, AIRegressionCase  # noqa: E402

SYNTHETIC_PREFIX = "SYN-"


def _infra_failure(error_code: str | None) -> bool:
    """基础设施失败没有可复现的能力缺陷，不能计入转化样本。"""
    if not error_code:
        return False
    category, _, _ = classify(str(error_code))
    return category in (ErrorClass.TRANSIENT_INFRA, ErrorClass.AMBIGUOUS_TIMEOUT)


def task_hash(task_id: str) -> str:
    """报告只保留来源任务哈希，不回显任务 ID。"""
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]


def percentile(values: list[float], p: float) -> float | None:
    """线性插值分位数；空样本返回 None，避免把缺失当 0。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _metric(values: list[float]) -> dict:
    within = sum(1 for value in values if value <= 24)
    return {
        "samples": len(values),
        "min": round(min(values), 2) if values else None,
        "p50": percentile(values, 0.5),
        "p90": percentile(values, 0.9),
        "max": round(max(values), 2) if values else None,
        "within_24h": within,
        "within_24h_rate": round(within / len(values), 3) if values else None,
        # 全样本都在 24h 内时，给出“超过 24h 比例”的单侧 95% 上界。
        "over_24h_upper_95": (round(1 - 0.05 ** (1 / len(values)), 3)
                              if values and within == len(values) else None),
    }


def summarize(rows: list[dict], *, window_days: int, excluded_synthetic: int,
              missing_source: int = 0, pending: list[dict] | None = None,
              excluded_infra: int = 0) -> dict:
    hours = [row["hours"] for row in rows]
    review_hours = [row["hours_review"] for row in rows]
    buckets = {"<=1h": 0, "<=8h": 0, "<=24h": 0, ">24h": 0}
    for value in hours:
        if value <= 1:
            buckets["<=1h"] += 1
        elif value <= 8:
            buckets["<=8h"] += 1
        elif value <= 24:
            buckets["<=24h"] += 1
        else:
            buckets[">24h"] += 1
    pending = pending or []
    return {
        "status": "OK" if rows else "NO_PRODUCTION_SAMPLES",
        "window_days": window_days,
        "samples": len(rows),
        "excluded_synthetic": excluded_synthetic,
        "excluded_infra": excluded_infra,
        "missing_source": missing_source,
        "hours": _metric(hours),
        "draft_to_approval": _metric(review_hours),
        "pending": {
            "samples": len(pending),
            "max_wait_hours": round(max((row["wait_hours"] for row in pending), default=0), 2),
            "over_24h": sum(1 for row in pending if row["wait_hours"] > 24),
        },
        "buckets": buckets,
        "note": ("没有生产差评/失败样本可供统计" if not rows else
                 "feedback：最早 DOWN 反馈（无反馈则任务创建）→ reviewed_at；"
                 "draft：用例 created_at → reviewed_at；pending 为仍在草稿阶段的等待时长"),
    }


def collect_rows(db, *, days: int = 90, exclude_synthetic: bool = True
                 ) -> tuple[list[dict], int, int, int]:
    """返回（有效行、排除的合成来源数、来源已删除数、排除的基础设施失败数）。"""
    conditions = [AIRegressionCase.status == "APPROVED",
                  AIRegressionCase.source_task_id.is_not(None),
                  AIRegressionCase.reviewed_at.is_not(None)]
    if days > 0:
        conditions.append(AIRegressionCase.reviewed_at >= datetime.now() - timedelta(days=days))
    rows: list[dict] = []
    excluded = 0
    missing = 0
    excluded_infra = 0
    for case in db.scalars(
            select(AIRegressionCase).where(*conditions).order_by(AIRegressionCase.reviewed_at.desc())
            .limit(1000)).all():
        task_id = str(case.source_task_id)
        if exclude_synthetic and task_id.startswith(SYNTHETIC_PREFIX):
            excluded += 1
            continue
        feedback_at = db.scalar(select(func.min(AIFeedback.created_at)).where(
            AIFeedback.task_id == task_id, AIFeedback.rating == "DOWN"))
        task = db.get(AIAgentTask, task_id)
        # 没有人工差评、只有 WORKER_UNAVAILABLE 等基础设施错误的用例不计入能力转化。
        if feedback_at is None and task is not None and _infra_failure(task.error_code):
            excluded_infra += 1
            continue
        started = feedback_at or (task.created_at if task is not None else None)
        if started is None:
            missing += 1
            continue
        rows.append({
            "case_key": case.case_key,
            "source_task_hash": task_hash(task_id),
            "started_at": started.isoformat(timespec="seconds"),
            "created_at": case.created_at.isoformat(timespec="seconds"),
            "reviewed_at": case.reviewed_at.isoformat(timespec="seconds"),
            "hours": round((case.reviewed_at - started).total_seconds() / 3600, 2),
            "hours_review": round((case.reviewed_at - case.created_at).total_seconds() / 3600, 2),
            "source": "feedback" if feedback_at is not None else "failure_task",
        })
    return rows, excluded, missing, excluded_infra


def collect_pending(db, *, days: int = 90, exclude_synthetic: bool = True) -> list[dict]:
    """草稿阶段仍在等待的用例；用当前时间计算已等待时长，不能当作已完成样本。"""
    now = datetime.now()
    conditions = [AIRegressionCase.status == "DRAFT",
                  AIRegressionCase.source_task_id.is_not(None)]
    if days > 0:
        conditions.append(AIRegressionCase.created_at >= now - timedelta(days=days))
    rows: list[dict] = []
    for case in db.scalars(
            select(AIRegressionCase).where(*conditions)
            .order_by(AIRegressionCase.created_at.asc()).limit(1000)).all():
        task_id = str(case.source_task_id)
        if exclude_synthetic and task_id.startswith(SYNTHETIC_PREFIX):
            continue
        rows.append({
            "case_key": case.case_key,
            "source_task_hash": task_hash(task_id),
            "created_at": case.created_at.isoformat(timespec="seconds"),
            "wait_hours": round((now - case.created_at).total_seconds() / 3600, 2),
        })
    return rows


def render_text(report: dict) -> str:
    if report["status"] == "NO_PRODUCTION_SAMPLES":
        pending = report["pending"]
        return "\n".join([
            "状态：NO_PRODUCTION_SAMPLES",
            f"窗口：最近 {report['window_days']} 天",
            f"已批准且带来源任务：0 条（排除合成 {report['excluded_synthetic']} 条，"
            f"基础设施失败 {report['excluded_infra']} 条，来源缺失 {report['missing_source']} 条）",
            f"仍在草稿阶段：{pending['samples']} 条，最长等待 {pending['max_wait_hours']} 小时",
            "说明：没有生产差评/失败样本可供统计，转化 ≤1 天无法判定；不要用 fixture 数据代替。",
        ])
    hours = report["hours"]
    review = report["draft_to_approval"]
    pending = report["pending"]
    return "\n".join([
        f"状态：OK（{report['samples']} 条已批准）",
        f"窗口：最近 {report['window_days']} 天"
        f"（排除合成 {report['excluded_synthetic']} 条，基础设施失败 {report['excluded_infra']} 条，"
        f"来源缺失 {report['missing_source']} 条）",
        f"反馈→批准（小时）：p50 {hours['p50']}，p90 {hours['p90']}，"
        f"24h 内 {hours['within_24h']}/{hours['samples']}",
        f"草稿→批准（小时）：p50 {review['p50']}，p90 {review['p90']}，"
        f"24h 内 {review['within_24h']}/{review['samples']}",
        f"超过 24h 比例的单侧 95% 上界：{hours['over_24h_upper_95']}",
        f"仍在草稿阶段：{pending['samples']} 条，最长等待 {pending['max_wait_hours']} 小时，"
        f"超 24h {pending['over_24h']} 条",
        "口径：反馈起点为最早 DOWN（无反馈则任务创建）；草稿起点为用例 created_at；默认排除 SYN-。",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=90, help="按 reviewed_at 回看天数，0 表示全部")
    parser.add_argument("--include-synthetic", action="store_true",
                        help="包含 SYN- 开头的 fixture；默认排除，避免污染生产结论")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--out", type=Path, help="写入 JSON 报告")
    args = parser.parse_args(argv)
    if args.days < 0:
        parser.error("--days 不能为负数")
    with SessionLocal() as db:
        rows, excluded, missing, excluded_infra = collect_rows(
            db, days=args.days, exclude_synthetic=not args.include_synthetic)
        pending = collect_pending(
            db, days=args.days, exclude_synthetic=not args.include_synthetic)
    report = {
        "kind": "production_regression_conversion",
        "data_source": "production_database",
        # 空样本时不能声称“已测量”，避免把 0 条当成 0 小时。
        "production_measured": bool(rows),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        **summarize(rows, window_days=args.days, excluded_synthetic=excluded,
                    missing_source=missing, pending=pending,
                    excluded_infra=excluded_infra),
        "pending_items": pending,
        "items": rows,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())