"""Agent 失败周报的确定性聚合与脱敏边界。"""

from types import SimpleNamespace

from app.modules.ai.failure_report import render_markdown, summarize


def test_summarize_groups_error_tool_prompt_and_feedback():
    tasks = [
        SimpleNamespace(id="task-a", error_code="TOOL_ERRORS", payload={
            "run_meta": {"prompt_versions": {"planner": "planner@1-aaa"},
                         "error": {"class": "BUSINESS_INVALID"}},
            "trace": [{"action": "call_tool", "tool": "purchase_orders.search"}],
        }),
        SimpleNamespace(id="task-b", error_code=None, payload={
            "run_meta": {"prompt_versions": {"planner": "planner@1-aaa"}},
            "trace": [{"action": "call_tool", "tool": "purchase_orders.search"}],
        }),
    ]
    feedbacks = [
        SimpleNamespace(rating="DOWN", reason_code="TOOL_ERROR"),
        SimpleNamespace(rating="UP", reason_code=None),
    ]

    report = summarize(tasks, feedbacks, days=7)

    assert report["tasks"] == 2
    assert report["failed_tasks"] == 1
    assert report["feedback"] == 2
    assert report["up"] == 1 and report["down"] == 1
    assert report["by_error_code"] == [{"key": "TOOL_ERRORS", "count": 1}]
    assert report["by_error_class"] == [{"key": "BUSINESS_INVALID", "count": 1}]
    assert report["by_tool"] == [{"key": "purchase_orders.search", "count": 2}]
    assert report["by_prompt_version"] == [{"key": "planner@1-aaa", "count": 2}]
    assert report["by_feedback_reason"] == [{"key": "TOOL_ERROR", "count": 1},
                                            {"key": "UNSPECIFIED", "count": 1}]
    assert report["samples"]["TOOL_ERRORS"] == ["task-a"]


def test_markdown_contains_counts_and_task_ids_without_user_content():
    report = summarize([], [], days=7)
    markdown = render_markdown(report)

    assert "最近 7 天" in markdown
    assert "任务数：0" in markdown
    assert "不保存提示词正文或用户原文" in markdown