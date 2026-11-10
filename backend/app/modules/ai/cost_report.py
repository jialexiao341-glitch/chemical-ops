"""Agent 任务 token 与费用聚合；只读任务记录，不调用模型。

费用只用于运营观察，不参与业务判断。缺少 usage 的历史任务只统计 token_budget 总量，
不伪造输入/输出拆分或费用；报告单独列出覆盖率。
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai.model import AIAgentTask


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


def summary(db: Session, *, days: int, price_in: float, price_out: float,
            default_model: str) -> dict:
    """读取时间窗口内的 Agent 任务并生成看板/CLI 共用报告。"""
    since = datetime.now() - timedelta(days=days)
    tasks = list(db.scalars(select(AIAgentTask).where(
        AIAgentTask.created_at >= since).order_by(AIAgentTask.created_at)).all())
    rows = collect_rows(tasks, price_in=price_in, price_out=price_out,
                        default_model=default_model)
    return build_report(rows, days=days, price_in=price_in, price_out=price_out,
                        default_model=default_model)