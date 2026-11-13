"""Agent 失败周报的确定性聚合与脱敏边界。"""

from types import SimpleNamespace

import pytest

from app.modules.ai_agent.shared_utils.error_policy import failure_stage
from app.modules.ai_agent.quality_operations.quality_report import render_markdown, summarize_failures as summarize


@pytest.mark.parametrize("code,stage", [
    ("INTENT_SCHEMA_ERROR", "routing"), ("MODEL_FORMAT_ERROR", "planner"),
    ("TOOL_TIMEOUT", "tool"), ("CONTEXT_LIMIT", "context"),
    ("INVALID_EVIDENCE", "confirm"), ("TOKEN_BUDGET_EXCEEDED", "budget"),
    ("DATABASE_ERROR", "infra"), (None, "unknown"), ("SOMETHING_NEW", "unknown"),
])
def test_failure_stage_is_deterministic_by_error_code(code, stage):
    assert failure_stage(code) == stage


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


def test_summarize_attributes_failure_stage_and_flags_case_conflicts():
    tasks = [
        SimpleNamespace(id="task-a", status="FAILED", error_code="INTENT_SCHEMA_ERROR",
                        payload={"run_meta": {}}),
        SimpleNamespace(id="task-b", status="SUCCEEDED", error_code=None,
                        payload={"run_meta": {}}),
    ]
    feedbacks = [
        SimpleNamespace(task_id="task-a", rating="UP", reason_code=None),
        SimpleNamespace(task_id="task-a", rating="DOWN", reason_code="WRONG_ANSWER"),
        SimpleNamespace(task_id="task-b", rating="DOWN", reason_code="MISSING_DATA"),
    ]

    report = summarize(tasks, feedbacks, days=7)

    assert report["by_failure_stage"] == [{"key": "routing", "count": 1}]
    assert report["available_failure_stages"] == ["routing"]
    assert report["case_conflict"]["total"] == 2
    assert report["case_conflict"]["ambiguous_rating"] == 1
    assert report["case_conflict"]["down_on_success"] == 1
    assert report["case_conflict"]["task_ids"] == ["task-a", "task-b"]

    markdown = render_markdown(report)
    assert "## 按失败阶段" in markdown
    assert "## 评价冲突" in markdown
    assert "冲突任务：task-a, task-b" in markdown