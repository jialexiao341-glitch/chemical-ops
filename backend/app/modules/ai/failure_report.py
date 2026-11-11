"""Agent 失败与反馈的确定性聚合；不调用模型，不输出用户身份或提示词正文。"""

from collections import Counter, defaultdict
from datetime import datetime

from app.modules.ai.error_policy import failure_stage


def summarize(tasks, feedbacks, *, days: int, limit: int = 10, filters: dict | None = None) -> dict:
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