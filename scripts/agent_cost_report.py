"""按场景、模型和 prompt 版本聚合 Agent 任务 token 与估算费用；只读数据库，不调用模型。

费用只用于运营观察，不参与业务判断。缺少 usage 的历史任务只统计 token 总量，
不伪造输入/输出拆分或费用；报告会单独列出覆盖率。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai.model import AIAgentTask  # noqa: E402


def _int(value: object) -> int:
    """只接受非负整数，避免布尔值或字符串污染汇总。"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def percentile(values: list[float], ratio: float) -> float | None:
    """线性插值分位数；空列表返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _scene(task: AIAgentTask) -> str:
    """场景取任务目标意图；旧任务可能没有记忆状态或意图。"""
    payload = task.payload or {}
    goal = ((payload.get("memory_state") or {}).get("goal") or {})
    intent = goal.get("intent")
    return intent if isinstance(intent, str) and intent and intent != "unknown" else "unknown"


def _prompt_version(meta: dict) -> str:
    versions = meta.get("prompt_versions") or {}
    if not isinstance(versions, dict):
        return "unknown"
    return str(versions.get("planner") or versions.get("routing") or "unknown")


def _usage_row(task: AIAgentTask, *, price_in: float, price_out: float,
               default_model: str) -> dict:
    """把单条任务归一成可聚合行；usage 缺失时保留 token_budget 总量并标记来源。"""
    payload = task.payload or {}
    meta = payload.get("run_meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    totals = meta.get("usage_totals") or {}
    if not isinstance(totals, dict):
        totals = {}
    budget = payload.get("token_budget") or {}
    if not isinstance(budget, dict):
        budget = {}

    calls = _int(totals.get("calls"))
    unmetered_calls = _int(totals.get("unmetered_calls"))
    split_unavailable_calls = _int(totals.get("split_unavailable_calls"))
    input_tokens = _int(totals.get("input_tokens"))
    output_tokens = _int(totals.get("output_tokens"))
    total_tokens = _int(totals.get("total_tokens"))
    budget_total = _int(budget.get("used_tokens"))

    if calls > 0 and unmetered_calls < calls:
        usage_source = "run_meta"
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
    elif budget_total > 0:
        usage_source = "token_budget"
        total_tokens = budget_total
    elif calls > 0:
        usage_source = "unmetered"
    else:
        usage_source = "missing"

    priced = price_in > 0 or price_out > 0
    cost = None
    cost_partial = split_unavailable_calls > 0
    if usage_source == "run_meta" and priced and (input_tokens or output_tokens):
        cost = round(input_tokens / 1_000_000 * price_in
                     + output_tokens / 1_000_000 * price_out, 6)
    duration = None
    if task.created_at and task.updated_at:
        seconds = (task.updated_at - task.created_at).total_seconds()
        if seconds >= 0:
            duration = round(seconds, 3)
    return {
        "task_id": task.id,
        "scene": "unknown",
        "model": str((meta.get("model") or {}).get("name") or default_model),
        "prompt_version": _prompt_version(meta),
        "status": task.status,
        "succeeded": task.status == "SUCCEEDED",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "budget_total_tokens": budget_total,
        "estimated_cost": cost,
        "cost_partial": cost_partial,
        "duration_seconds": duration,
        "usage_source": usage_source,
        "calls": calls,
        "unmetered_calls": unmetered_calls,
        "split_unavailable_calls": split_unavailable_calls,
    }


def collect_rows(tasks, *, price_in: float, price_out: float, default_model: str) -> list[dict]:
    """把 ORM 任务或同结构对象归一成报告行。"""
    rows = []
    for task in tasks:
        row = _usage_row(task, price_in=price_in, price_out=price_out,
                         default_model=default_model)
        row["scene"] = _scene(task)
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    """汇总一组任务：成功率、token、已知费用和耗时 P50/P95。

    耗时只统计已终止任务；等待补充或运行中的 updated_at 不是完成时间。
    """
    terminal_statuses = {"SUCCEEDED", "FAILED", "CANCELLED"}
    durations = [row["duration_seconds"] for row in rows
                 if row.get("status") in terminal_statuses
                 and isinstance(row.get("duration_seconds"), (int, float))]
    costs = [row["estimated_cost"] for row in rows
             if isinstance(row.get("estimated_cost"), (int, float))]
    succeeded = sum(1 for row in rows if row.get("succeeded"))
    total = len(rows)
    return {
        "tasks": total,
        "terminal_tasks": sum(1 for row in rows if row.get("status") in terminal_statuses),
        "succeeded": succeeded,
        "success_rate": round(succeeded / total, 4) if total else None,
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "total_tokens": sum(row["total_tokens"] for row in rows),
        "estimated_cost": round(sum(costs), 6) if costs else None,
        "cost_tasks": len(costs),
        "cost_missing_tasks": total - len(costs),
        "partial_cost_tasks": sum(1 for row in rows if row.get("cost_partial")),
        "p50_seconds": round(percentile(durations, 0.5), 3) if durations else None,
        "p95_seconds": round(percentile(durations, 0.95), 3) if durations else None,
    }


def _group(rows: list[dict], key: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    groups = [{key: name, **summarize(items)} for name, items in grouped.items()]
    return sorted(groups, key=lambda item: (-item["total_tokens"], -item["tasks"], item[key]))


def build_report(rows: list[dict], *, days: int, price_in: float, price_out: float,
                 default_model: str) -> dict:
    """生成 JSON 报告；不包含任务原文和用户身份。"""
    terminal = {"SUCCEEDED", "FAILED", "CANCELLED"}
    coverage = {
        "tasks": len(rows),
        "terminal_tasks": sum(1 for row in rows if row.get("status") in terminal),
        "run_meta_usage": sum(1 for row in rows if row["usage_source"] == "run_meta"),
        "token_budget_only": sum(1 for row in rows if row["usage_source"] == "token_budget"),
        "unmetered": sum(1 for row in rows if row["usage_source"] == "unmetered"),
        "missing": sum(1 for row in rows if row["usage_source"] == "missing"),
        "calls": sum(row["calls"] for row in rows),
        "unmetered_calls": sum(row["unmetered_calls"] for row in rows),
        "split_unavailable_calls": sum(row["split_unavailable_calls"] for row in rows),
        "tasks_with_duration": sum(1 for row in rows
                                   if row.get("status") in terminal
                                   and isinstance(row.get("duration_seconds"), (int, float))),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "default_model": default_model,
        "pricing": {
            "input_per_million": price_in,
            "output_per_million": price_out,
            "configured": price_in > 0 or price_out > 0,
        },
        "scope": "只读 AIAgentTask.payload；按场景、模型和 prompt 版本聚合，不含任务原文和用户身份。",
        "summary": summarize(rows),
        "by_scene": _group(rows, "scene"),
        "by_model": _group(rows, "model"),
        "by_prompt_version": _group(rows, "prompt_version"),
        "coverage": coverage,
        "notes": [
            "费用按配置的每百万输入/输出 token 单价估算，不参与业务判断。",
            "缺少 run_meta.usage_totals 的任务只统计 token_budget 总量，不估算费用。",
            "一次任务包含多次模型调用；usage_totals 由运行时累计，不是最后一次调用。",
        ],
    }


def _fmt(value: object, digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _rate(value: object) -> str:
    return "—" if value is None else f"{float(value):.1%}"


def render_markdown(report: dict) -> str:
    """生成可直接贴入周报的 Markdown；费用列为估算值。"""
    pricing = report["pricing"]
    lines = [
        f"# Agent token 与费用报告（最近 {report['days']} 天）",
        "",
        "范围：只读任务运行元数据，按场景、模型和 prompt 版本聚合；不含用户身份和任务原文。",
        f"单价：输入 {pricing['input_per_million']} / 百万 token，输出 "
        f"{pricing['output_per_million']} / 百万 token"
        + ("" if pricing["configured"] else "（未配置，费用不估算）"),
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
    ]
    summary = report["summary"]
    lines += [
        f"| 任务数 | {summary['tasks']} |",
        f"| 成功 / 成功率 | {summary['succeeded']} / {_rate(summary['success_rate'])} |",
        f"| 输入 token | {_fmt(summary['input_tokens'])} |",
        f"| 输出 token | {_fmt(summary['output_tokens'])} |",
        f"| 总 token | {_fmt(summary['total_tokens'])} |",
        f"| 估算费用 | {_fmt(summary['estimated_cost'], 4)} |",
        f"| P50 / P95 墙钟耗时（秒） | {_fmt(summary['p50_seconds'], 2)} / "
        f"{_fmt(summary['p95_seconds'], 2)} |",
    ]
    for title, key, field in (("按场景", "by_scene", "scene"),
                              ("按模型", "by_model", "model"),
                              ("按 prompt 版本", "by_prompt_version", "prompt_version")):
        lines += ["", f"## {title}", "",
                  f"| {title[1:].strip()} | 任务 | 成功率 | 输入 token | 输出 token | 总 token | 估算费用 | P50 | P95 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        rows = report.get(key) or []
        if not rows:
            lines.append("| 无 | 0 | — | 0 | 0 | 0 | — | — | — |")
        for row in rows:
            lines.append(
                f"| {row[field]} | {row['tasks']} | {_rate(row['success_rate'])} | "
                f"{_fmt(row['input_tokens'])} | {_fmt(row['output_tokens'])} | "
                f"{_fmt(row['total_tokens'])} | {_fmt(row['estimated_cost'], 4)} | "
                f"{_fmt(row['p50_seconds'], 2)} | {_fmt(row['p95_seconds'], 2)} |")
    coverage = report["coverage"]
    lines += [
        "", "## 覆盖率", "",
        f"- 有 run_meta 用量：{coverage['run_meta_usage']} / {coverage['tasks']}",
        f"- 只有 token_budget 总量：{coverage['token_budget_only']}",
        f"- 无用量：{coverage['unmetered']}；无任务记录：{coverage['missing']}",
        f"- 模型调用 {coverage['calls']} 次，其中缺 usage {coverage['unmetered_calls']} 次、"
        f"缺输入/输出拆分 {coverage['split_unavailable_calls']} 次",
        "",
        "费用只按有输入/输出拆分的任务估算；`token_budget` 旧任务不伪造费用。",
        f"耗时只统计已终止任务（{coverage['tasks_with_duration']} / {coverage['terminal_tasks']}）；"
        "按 created_at→updated_at 的墙钟计算，包含排队和等待续答，不是单次模型调用延迟。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="统计窗口天数")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/agent-cost-report.json",
                        help="JSON 报告路径")
    parser.add_argument("--markdown", type=Path, default=None,
                        help="Markdown 路径；默认与 JSON 同名 .md")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("days 必须为正数")

    settings = get_settings()
    since = datetime.now() - timedelta(days=args.days)
    with SessionLocal() as db:
        tasks = list(db.scalars(select(AIAgentTask).where(
            AIAgentTask.created_at >= since).order_by(AIAgentTask.created_at)).all())
    rows = collect_rows(tasks, price_in=settings.llm_price_input_per_million,
                        price_out=settings.llm_price_output_per_million,
                        default_model=settings.llm_model)
    report = build_report(rows, days=args.days,
                          price_in=settings.llm_price_input_per_million,
                          price_out=settings.llm_price_output_per_million,
                          default_model=settings.llm_model)
    output = args.output
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({
        "tasks": report["summary"]["tasks"],
        "coverage": report["coverage"],
        "output": str(output),
        "markdown": str(markdown),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())