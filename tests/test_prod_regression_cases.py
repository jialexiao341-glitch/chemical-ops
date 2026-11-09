"""生产差评转回归用例与路由回放契约。"""

from types import SimpleNamespace

import pytest

from scripts import evaluate_prod_regression as prod_eval
from scripts import promote_agent_case as promote


def _task():
    return SimpleNamespace(
        id="task-123456", payload={
            "messages": ["列出逾期订单"],
            "trace": [
                {"action": "call_tool", "tool": "purchase_orders.search"},
                {"action": "finish"},
            ],
            "run_meta": {"prompt_versions": {"planner": "planner@1-abc"}},
        })


def test_build_case_derives_task_and_hashes_source():
    case = promote.build_case(_task(), question="列一下逾期的采购订单",
                              expected_mode="agent", expected_tasks=[],
                              forbidden_tasks=["analytics"], note="差评转正")

    assert case["id"].startswith("PR-")
    assert case["expected_tasks"] == ["order_search"]
    assert case["forbidden_tasks"] == ["analytics"]
    assert len(case["source_task_hash"]) == 12
    assert case["source_prompt_version"] == "planner@1-abc"
    assert "task-123456" not in str(case)


def test_build_case_requires_derivable_or_explicit_task():
    task = SimpleNamespace(id="t", payload={"messages": ["你好"], "trace": [], "run_meta": {}})
    with pytest.raises(ValueError, match="无法从任务轨迹推导"):
        promote.build_case(task, question="你好", expected_mode="none",
                           expected_tasks=[], forbidden_tasks=[])


def test_append_case_rejects_duplicate_id_or_source(tmp_path):
    path = tmp_path / "cases.json"
    case = {"id": "PR-1", "source_task_hash": "abc", "question": "q"}
    promote.append_case(path, case)
    with pytest.raises(ValueError, match="已存在"):
        promote.append_case(path, {**case})
    with pytest.raises(ValueError, match="已登记"):
        promote.append_case(path, {**case, "id": "PR-2"})


def test_check_decision_passes_only_expected_and_allowed_tasks():
    case = {"expected_execution_mode": "agent",
            "expected_tasks": ["order_search"],
            "forbidden_tasks": ["analytics"]}
    good = SimpleNamespace(execution_mode="agent", tasks=["order_search"])
    assert prod_eval.check_decision(good, case)["passed"] is True

    wrong_mode = SimpleNamespace(execution_mode="query", tasks=["order_search"])
    assert prod_eval.check_decision(wrong_mode, case)["passed"] is False

    forbidden = SimpleNamespace(execution_mode="agent", tasks=["order_search", "analytics"])
    checks = prod_eval.check_decision(forbidden, case)
    assert checks["passed"] is False and checks["forbidden_tasks"] is False