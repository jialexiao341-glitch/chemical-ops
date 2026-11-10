"""Agent 质量与失败证据聚合；只读任务和反馈，不调用模型、不返回用户原文。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai import failure_report
from app.modules.ai.model import AIAgentTask, AIFeedback

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
    report = failure_report.summarize(tasks, feedbacks, days=days, limit=limit, filters=filters)
    report.update({
        "truncated": truncated,
        "available_prompt_versions": available_prompt_versions,
        "available_models": available_models,
        "available_tools": available_tools,
        "available_error_classes": available_error_classes,
        "available_error_codes": available_error_codes,
    })
    return report
