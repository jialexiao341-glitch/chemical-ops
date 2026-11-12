"""生产差评转回归用例与路由回放契约。"""

import json
from types import SimpleNamespace

import pytest

from scripts import evaluate_prod_regression as prod_eval
from scripts import promote_agent_case as promote


def _row(case_id: str, *, passed: bool, question: str = "查逾期采购订单",
         actual_mode: str = "agent", actual_tasks: list[str] | None = None,
         trace: list[dict] | None = None) -> dict:
    return {
        "id": case_id,
        "question": question,
        "passed": passed,
        "status": "SUCCEEDED" if passed else "FAILED",
        "actual_mode": actual_mode,
        "actual_tasks": ["order_search"] if actual_tasks is None else actual_tasks,
        "rounds": [{"passed": passed, "trace": trace if trace is not None else [
            {"action": "call_tool", "tool": "purchase_orders.search"}]}],
    }


def _report(tmp_path, rows: list[dict]):
    path = tmp_path / "agent_business.json"
    path.write_text(json.dumps({"prompt_versions": {"planner": "planner@1-x"},
                                "cases": rows}, ensure_ascii=False), encoding="utf-8")
    return path


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
    # 不执行任务的场景允许没有预期任务；需要执行时必须能推导出任务或显式给出。
    case = promote.build_case(task, question="你好", expected_mode="none",
                              expected_tasks=[], forbidden_tasks=[])
    assert case["expected_tasks"] == []
    with pytest.raises(ValueError, match="无法从任务轨迹推导"):
        promote.build_case(task, question="你好", expected_mode="agent",
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


def test_case_failed_ignores_rounds_without_passed_field():
    """业务报告的 rounds 是轨迹轮次，没有 passed 字段，不能被判成失败。"""
    row = {"passed": True, "rounds": [{"status": "SUCCEEDED", "reply": "ok"}]}
    failed_round = {"rounds": [{"status": "FAILED"}]}
    assert promote.case_failed(row) is False
    assert promote.case_failed(failed_round) is False
    assert promote.case_failed({"passed": False}) is True
    assert promote.case_failed({"passed": True, "rounds": [{"passed": False}]}) is True


def test_resolve_tasks_derives_from_required_tools():
    row = {"required_tools": ["catalog.search_products", "inventory.query_available"]}
    assert promote.resolve_tasks(row, []) == ["inventory"]
    assert promote.resolve_tasks({"actual_tasks": ["quotes"]}, []) == ["quotes"]
    assert promote.resolve_tasks(row, ["order_search"]) == ["order_search"]


def test_select_report_rows_filters_failed_or_explicit_ids():
    rows = [_row("B001", passed=False), _row("B002", passed=True),
            _row("B003", passed=False, question="查甲醇库存")]
    assert [row["id"] for row in promote.select_report_rows(rows, failed_only=True)] == [
        "B001", "B003"]
    assert [row["id"] for row in promote.select_report_rows(rows, case_ids=["B002"])] == ["B002"]
    with pytest.raises(ValueError, match="没有匹配的用例"):
        promote.select_report_rows(rows, case_ids=["B999"])


def test_batch_promote_writes_cases_and_skips_duplicates_on_rerun(tmp_path, capsys):
    report = _report(tmp_path, [_row("B001", passed=False),
                                _row("B002", passed=True),
                                _row("B003", passed=False, question="查甲醇库存")])
    output = tmp_path / "cases.json"
    argv = ["--report", str(report), "--failed-only", "--allow-raw-question",
            "--expected-mode", "auto", "--output", str(output)]

    code = promote.main(argv)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in payload["written"]] == [
        promote.build_case(promote.task_from_report(report, "B001"),
                           question="查逾期采购订单", expected_mode="agent",
                           expected_tasks=[],
                           forbidden_tasks=[])["id"],
        promote.build_case(promote.task_from_report(report, "B003"),
                           question="查甲醇库存", expected_mode="agent",
                           expected_tasks=[],
                           forbidden_tasks=[])["id"],
    ]
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert len(stored) == 2
    assert all(case["expected_execution_mode"] == "agent" for case in stored)

    code = promote.main(argv)
    assert code == 0
    rerun = json.loads(capsys.readouterr().out)
    assert rerun["written"] == []
    assert len(rerun["skipped"]) == 2


def test_batch_dry_run_does_not_write_file(tmp_path, capsys):
    report = _report(tmp_path, [_row("B001", passed=False)])
    output = tmp_path / "cases.json"

    code = promote.main(["--report", str(report), "--failed-only",
                         "--allow-raw-question", "--dry-run", "--output", str(output)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert len(payload["written"]) == 1
    assert not output.exists()


def test_batch_auto_mode_uses_row_actual_mode(tmp_path, capsys):
    report = _report(tmp_path, [_row("B001", passed=False, actual_mode="query",
                                     actual_tasks=["analytics"])])
    output = tmp_path / "cases.json"

    promote.main(["--report", str(report), "--failed-only", "--allow-raw-question",
                  "--expected-mode", "auto", "--output", str(output)])
    capsys.readouterr()

    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored[0]["expected_execution_mode"] == "query"
    assert stored[0]["expected_tasks"] == ["analytics"]


def test_batch_keeps_going_when_one_case_cannot_derive_tasks(tmp_path, capsys):
    report = _report(tmp_path, [
        _row("B001", passed=False),
        _row("B002", passed=False, question="你好", actual_mode="agent",
             actual_tasks=[], trace=[]),
    ])
    output = tmp_path / "cases.json"

    code = promote.main(["--report", str(report), "--failed-only", "--allow-raw-question",
                         "--expected-mode", "agent", "--output", str(output)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["written"]) == 1
    assert payload["failed"][0]["id"] == "B002"
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 1


def test_batch_requires_explicit_raw_question_consent(tmp_path):
    report = _report(tmp_path, [_row("B001", passed=False)])

    code = promote.main(["--report", str(report), "--failed-only",
                         "--output", str(tmp_path / "cases.json")])

    assert code == 1
