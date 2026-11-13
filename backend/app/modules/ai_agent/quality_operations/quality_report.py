"""Agent 质量报告：筛选任务、聚合失败与反馈，并生成脱敏报告。

数据库读取和纯聚合保持独立函数，报告不调用模型，也不输出用户原文。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai_agent.shared_utils.error_policy import failure_stage
from app.modules.ai_agent.model import AIAgentTask, AIFeedback

MAX_TASKS = 5000


def _meta(task) -> dict:
    payload = task.payload or {}
    meta = payload.get("run_meta") or {}
    return meta if isinstance(meta, dict) else {}


def _trace_tools(task) -> set[str]:
    payload = task.payload or {}
    return {
        str(entry["tool"])
        for entry in payload.get("trace") or []
        if isinstance(entry, dict) and entry.get("action") == "call_tool" and entry.get("tool")
    }


def _prompt_versions(task) -> set[str]:
    versions = _meta(task).get("prompt_versions") or {}
    if not isinstance(versions, dict):
        return set()
    return {str(value) for value in versions.values() if isinstance(value, str) and value}


def _error_class(task) -> str | None:
    error = _meta(task).get("error") or {}
    value = error.get("class") if isinstance(error, dict) else None
    return str(value) if isinstance(value, str) and value else None


def _model(task) -> str | None:
    value = (_meta(task).get("model") or {}).get("name")
    return str(value) if isinstance(value, str) and value else None


def _selected(task, *, prompt_version: str | None, error_class: str | None,
              tool: str | None) -> bool:
    if prompt_version and prompt_version not in _prompt_versions(task):
        return False
    if error_class and _error_class(task) != error_class:
        return False
    return not (tool and tool not in _trace_tools(task))


def summarize(db: Session, *, days: int = 7, limit: int = 10,
              prompt_version: str | None = None, error_class: str | None = None,
              tool: str | None = None, rating: str | None = None) -> dict:
    """返回可筛选的质量聚合；工具、错误类别和 prompt 版本来自现有任务元数据。"""
    since = datetime.now() - timedelta(days=days)
    rows = list(db.scalars(
        select(AIAgentTask)
        .where(AIAgentTask.created_at >= since)
        .order_by(AIAgentTask.created_at.desc())
        .limit(MAX_TASKS + 1)
    ).all())
    truncated = len(rows) > MAX_TASKS
    rows = rows[:MAX_TASKS]

    available_prompt_versions = sorted({version for task in rows for version in _prompt_versions(task)})
    available_models = sorted({model for task in rows if (model := _model(task))})
    available_tools = sorted({tool_name for task in rows for tool_name in _trace_tools(task)})
    available_error_classes = sorted({value for task in rows if (value := _error_class(task))})
    available_error_codes = sorted({str(task.error_code) for task in rows if task.error_code})

    task_filters_active = bool(prompt_version or error_class or tool)
    tasks = [task for task in rows if _selected(
        task, prompt_version=prompt_version, error_class=error_class, tool=tool)]

    feedback_query = select(AIFeedback).where(AIFeedback.created_at >= since)
    if task_filters_active:
        task_ids = {task.id for task in tasks}
        feedbacks = [] if not task_ids else list(db.scalars(
            feedback_query.where(AIFeedback.task_id.in_(task_ids))).all())
    else:
        feedbacks = list(db.scalars(feedback_query).all())
    if rating:
        feedbacks = [feedback for feedback in feedbacks if feedback.rating == rating]
        # 选择“有帮助/没帮助”时，任务统计也只保留有对应反馈的任务。
        rated_task_ids = {feedback.task_id for feedback in feedbacks}
        tasks = [task for task in tasks if task.id in rated_task_ids]

    filters = {
        "prompt_version": prompt_version,
        "error_class": error_class,
        "tool": tool,
        "rating": rating,
    }
    report = summarize_failures(tasks, feedbacks, days=days, limit=limit, filters=filters)
    report.update({
        "truncated": truncated,
        "available_prompt_versions": available_prompt_versions,
        "available_models": available_models,
        "available_tools": available_tools,
        "available_error_classes": available_error_classes,
        "available_error_codes": available_error_codes,
    })
    return report


def summarize_failures(tasks, feedbacks, *, days: int, limit: int = 10, filters: dict | None = None) -> dict:
    """按错误码、失败阶段、工具、prompt 版本和反馈原因聚合，并标记评价冲突任务。"""
    by_error_code: Counter[str] = Counter()
    by_error_class: Counter[str] = Counter()
    by_recovery: Counter[str] = Counter()
    by_tool: Counter[str] = Counter()
    by_prompt_version: Counter[str] = Counter()
    by_model: Counter[str] = Counter()
    by_feedback_reason: Counter[str] = Counter()
    by_feedback_rating: Counter[str] = Counter()
    by_failure_stage: Counter[str] = Counter()
    failed_tasks: list[str] = []
    samples: dict[str, list[str]] = {}
    available_prompt_versions: set[str] = set()
    available_models: set[str] = set()
    available_tools: set[str] = set()
    available_error_classes: set[str] = set()
    available_failure_stages: set[str] = set()
    task_status: dict[str, str] = {}
    ratings_by_task: dict[str, set[str]] = defaultdict(set)

    for task in tasks:
        payload = task.payload or {}
        meta = payload.get("run_meta") or {}
        task_status[str(task.id)] = str(getattr(task, "status", "") or "")
        if task.error_code:
            by_error_code[task.error_code] += 1
            failed_tasks.append(task.id)
            stage = failure_stage(task.error_code)
            by_failure_stage[stage] += 1
            available_failure_stages.add(stage)
            bucket = samples.setdefault(task.error_code, [])
            if len(bucket) < 5:
                bucket.append(task.id)
        error = meta.get("error") or {}
        error_class = error.get("class")
        if error_class:
            by_error_class[str(error_class)] += 1
            available_error_classes.add(str(error_class))
        recovery = error.get("recovery")
        if recovery:
            by_recovery[str(recovery)] += 1
        versions = meta.get("prompt_versions") or {}
        if isinstance(versions, dict):
            available_prompt_versions.update(
                str(value) for value in versions.values() if isinstance(value, str) and value)
        version = ((meta.get("prompt_versions") or {}).get("planner")
                   or (meta.get("prompt_versions") or {}).get("routing")
                   or "unknown")
        by_prompt_version[str(version)] += 1
        model = ((meta.get("model") or {}).get("name")) or "unknown"
        by_model[str(model)] += 1
        available_models.add(str(model))
        for entry in payload.get("trace") or []:
            if entry.get("action") == "call_tool" and entry.get("tool"):
                tool = str(entry["tool"])
                by_tool[tool] += 1
                available_tools.add(tool)

    for feedback in feedbacks:
        by_feedback_reason[feedback.reason_code or "UNSPECIFIED"] += 1
        by_feedback_rating[feedback.rating] += 1
        task_id = getattr(feedback, "task_id", None)
        if task_id:
            ratings_by_task[str(task_id)].add(str(feedback.rating))

    ambiguous_rating = sorted(
        task_id for task_id, ratings in ratings_by_task.items() if {"UP", "DOWN"} <= ratings)
    down_on_success = sorted(
        task_id for task_id, ratings in ratings_by_task.items()
        if "DOWN" in ratings and task_status.get(task_id) == "SUCCEEDED")
    conflict_ids = sorted(set(ambiguous_rating) | set(down_on_success))

    total_feedback = len(feedbacks)
    down = by_feedback_rating.get("DOWN", 0)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "filters": filters or {},
        "tasks": len(tasks),
        "failed_tasks": len(failed_tasks),
        "feedback": total_feedback,
        "up": by_feedback_rating.get("UP", 0),
        "down": down,
        "down_rate": round(down / total_feedback, 4) if total_feedback else None,
        "by_error_code": _top(by_error_code, limit),
        "by_error_class": _top(by_error_class, limit),
        "by_failure_stage": _top(by_failure_stage, limit),
        "by_recovery": _top(by_recovery, limit),
        "by_tool": _top(by_tool, limit),
        "by_prompt_version": _top(by_prompt_version, limit),
        "by_model": _top(by_model, limit),
        "by_feedback_reason": _top(by_feedback_reason, limit),
        "failed_task_ids": failed_tasks[:50],
        "samples": samples,
        "case_conflict": {
            "total": len(conflict_ids),
            "ambiguous_rating": len(ambiguous_rating),
            "down_on_success": len(down_on_success),
            "task_ids": conflict_ids[:50],
            "note": "只标记评价与状态不一致；不判定用户或系统哪一方错误",
        },
        "available_prompt_versions": sorted(available_prompt_versions),
        "available_models": sorted(available_models),
        "available_tools": sorted(available_tools),
        "available_error_classes": sorted(available_error_classes),
        "available_failure_stages": sorted(available_failure_stages),
    }


def _top(counter: Counter[str], limit: int) -> list[dict[str, int | str]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def render_markdown(report: dict) -> str:
    """生成可直接贴入周报的 Markdown；不含任务原文和用户身份。"""
    down_rate = report.get("down_rate")
    down_rate_text = f"，差评率 {down_rate:.1%}" if isinstance(down_rate, (int, float)) else ""
    lines = [
        f"# Agent 失败与反馈周报（最近 {report['days']} 天）",
        "",
        f"- 任务数：{report['tasks']}",
        f"- 失败任务：{report['failed_tasks']}",
        f"- 反馈数：{report['feedback']}（有帮助 {report['up']} / 没帮助 {report['down']}）{down_rate_text}",
        "",
    ]
    sections = [
        ("按错误码", "by_error_code"),
        ("按错误类别", "by_error_class"),
        ("按失败阶段", "by_failure_stage"),
        ("按恢复建议", "by_recovery"),
        ("按工具调用", "by_tool"),
        ("按 prompt 版本", "by_prompt_version"),
        ("按模型", "by_model"),
        ("按反馈原因", "by_feedback_reason"),
    ]
    for title, key in sections:
        lines += [f"## {title}", "", "| 项 | 次数 |", "| --- | ---: |"]
        rows = report.get(key) or []
        if not rows:
            lines.append("| 无 | 0 |")
        for row in rows:
            lines.append(f"| {row['key']} | {row['count']} |")
        lines.append("")
    conflict = report.get("case_conflict") or {}
    lines += ["## 评价冲突", "", "| 类型 | 任务数 |", "| --- | ---: |",
              f"| 同一任务同时有帮助/没帮助 | {conflict.get('ambiguous_rating', 0)} |",
              f"| 标记没帮助但状态成功 | {conflict.get('down_on_success', 0)} |",
              f"| 去重合计 | {conflict.get('total', 0)} |", ""]
    if conflict.get("task_ids"):
        lines += [f"- 冲突任务：{', '.join(conflict['task_ids'])}", ""]
    lines += ["## 失败样本任务编号", ""]
    samples = report.get("samples") or {}
    if not samples:
        lines.append("无")
    for code, ids in samples.items():
        lines.append(f"- `{code}`：{', '.join(ids)}")
    lines.append("")
    lines.append("说明：样本只含任务编号；回看内容仍需本人权限，报告不保存提示词正文或用户原文。")
    lines.append("评价冲突只表示评价与状态不一致，不判定用户或系统哪一方错误。")
    return "\n".join(lines)