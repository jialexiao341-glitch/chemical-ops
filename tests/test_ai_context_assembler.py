"""规划上下文的预算、保真和不可变性。"""

import copy
import json

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai.context_assembler import assemble_planner_context, estimate_tokens


@pytest.mark.parametrize(("text", "expected"), [("", 0), ("中文测试", 4), ("abcdefgh", 2), ("中文abcd", 3), ("a" * 10001, 2501)])
def test_token_estimation(text, expected):
    assert estimate_tokens(text) == expected


def test_short_context_is_unchanged():
    payload = {"messages": ["查询库存"], "tools": [], "current_turn_steps": [], "recent_task_memory": {"goal": {"intent": "inventory"}}}
    context, stats = assemble_planner_context(payload, max_tokens=12000, max_chars=18000)
    assert json.loads(context) == payload
    assert stats.truncated_sections == []
    assert stats.estimated_tokens == estimate_tokens(context)


def test_large_context_retains_verified_facts_and_step_references():
    payload = {"messages": ["历史" * 1200 for _ in range(40)] + ["查询乙醇库存"],
        "tools": [{"name": "inventory", "input_schema": {"type": "object"}}],
        "recent_task_memory": {"goal": {"intent": "inventory", "description": "查询乙醇库存"},
            "focus": {"product_name": "乙醇"}, "slots": {"warehouse": 2},
            "pending": {"entity": "product"}, "evidence_ref": {"trace_steps": [1, 2]},
            "recent_context": [{"role": "user", "text": "历史" * 500} for _ in range(20)]},
        "verified_product_id": 11,
        "current_turn_steps": [{"step": i, "action": "call_tool", "tool": "inventory", "status": "SUCCEEDED",
            "result": {"product_id": 11, "total_rows": 100, "totals": [{"unit": "kg", "available_quantity": "100"}],
                       "rows": [{"batch": "a" * 100} for _ in range(100)], "sources": [{"record_id": j} for j in range(100)]}}
            for i in range(1, 6)]}
    original = copy.deepcopy(payload)
    context, stats = assemble_planner_context(payload, max_tokens=4000, max_chars=12000)
    result = json.loads(context)
    assert stats.estimated_tokens <= 4000 and len(context) <= 12000
    assert result["messages"][-1] == "查询乙醇库存"
    assert result["verified_product_id"] == 11
    assert result["recent_task_memory"]["goal"]["intent"] == "inventory"
    assert result["recent_task_memory"]["slots"]["warehouse"] == 2
    assert result["recent_task_memory"]["pending"]["entity"] == "product"
    assert result["recent_task_memory"]["evidence_ref"]["trace_steps"] == [1, 2]
    assert [step["step"] for step in result["current_turn_steps"]] == list(range(1, 6))
    assert all(step["result"]["totals"][0]["available_quantity"] == "100" for step in result["current_turn_steps"])
    assert stats.truncated_sections
    assert payload == original


def test_mandatory_context_that_cannot_fit_fails_safely():
    with pytest.raises(BusinessValidationError, match="CONTEXT_LIMIT"):
        assemble_planner_context({"messages": ["查询"], "tools": []}, max_tokens=1, max_chars=10)


def test_each_large_result_is_limited_even_when_total_would_fit():
    payload = {"messages": ["查询"], "tools": [], "current_turn_steps": [
        {"step": 1, "action": "call_tool", "tool": "inventory", "status": "SUCCEEDED",
         "result": {"product_id": 1, "total_rows": 100, "rows": [{"name": "中" * 1000} for _ in range(5)]}}]}
    context, stats = assemble_planner_context(payload, max_tokens=8000, max_chars=18000)
    result = json.loads(context)["current_turn_steps"][0]["result"]
    assert estimate_tokens(json.dumps(result, ensure_ascii=False)) <= 2000
    assert "tool_results" in stats.truncated_sections


def test_precompacted_results_are_counted_as_truncated():
    payload = {"current_turn_steps": [{"step": 1, "action": "call_tool", "result": {"planner_truncated": True}}]}
    _, stats = assemble_planner_context(payload, max_tokens=12000, max_chars=18000)
    assert stats.truncated_sections == ["tool_results"]
