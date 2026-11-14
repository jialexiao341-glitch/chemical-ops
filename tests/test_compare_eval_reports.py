"""评测对比门禁：只解析本地 JSON，区分退化、改善与安全回归。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import compare_eval_reports as compare

FIXTURES = Path(__file__).with_name("fixtures")
BASELINE = FIXTURES / "eval-report-baseline.json"
CANDIDATE = FIXTURES / "eval-report-candidate.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _report(cases: list[dict]) -> dict:
    return {"model": "fixture", "dataset_version": "fixture-v1", "cases": cases}


def test_fixture_reports_expose_specific_regression_and_safety_failure():
    result = compare.compare(_load(BASELINE), _load(CANDIDATE))

    assert [row["key"] for row in result["regressions"]] == ["S01"]
    assert result["regressions"][0]["safety"] is True
    assert result["regressions"][0]["failed_checks"] == ["safe_boundary"]
    assert [row["key"] for row in result["improvements"]] == ["T02"]
    assert [row["key"] for row in result["safety_failures"]] == ["S01"]
    assert result["pass_rate_delta_points"] == 0.0
    assert result["verdict"] == "REGRESSION"


def test_business_trials_are_aggregated_per_case():
    baseline = _report([
        {"id": "B01", "trial": 1, "group": "inventory", "safety": False, "passed": True,
         "checks": {"outcome": True}},
        {"id": "B01", "trial": 2, "group": "inventory", "safety": False, "passed": True,
         "checks": {"outcome": True}},
        {"id": "B02", "trial": 1, "group": "quotes", "safety": False, "passed": False,
         "checks": {"outcome": False}},
    ])
    candidate = _report([
        {"id": "B01", "trial": 1, "group": "inventory", "safety": False, "passed": True,
         "checks": {"outcome": True}},
        {"id": "B01", "trial": 2, "group": "inventory", "safety": False, "passed": False,
         "checks": {"outcome": False}},
        {"id": "B02", "trial": 1, "group": "quotes", "safety": False, "passed": True,
         "checks": {"outcome": True}},
    ])

    result = compare.compare(baseline, candidate)

    assert [row["key"] for row in result["regressions"]] == ["B01"]
    assert result["regressions"][0]["failed_runs"] == [2]
    assert [row["key"] for row in result["improvements"]] == ["B02"]


def test_intent_rounds_aggregate_per_question_and_list_added_cases():
    baseline = _report([
        {"question": "q1", "round": 1, "passed": True},
        {"question": "q1", "round": 2, "passed": True},
        {"question": "q2", "round": 1, "passed": False},
    ])
    candidate = _report([
        {"question": "q1", "round": 1, "passed": True},
        {"question": "q1", "round": 2, "passed": False},
        {"question": "q2", "round": 1, "passed": True},
        {"question": "q3", "round": 1, "passed": True},
    ])

    result = compare.compare(baseline, candidate)

    assert [row["key"] for row in result["regressions"]] == ["q1"]
    assert result["regressions"][0]["failed_runs"] == [2]
    assert [row["key"] for row in result["improvements"]] == ["q2"]
    assert [row["key"] for row in result["added"]] == ["q3"]


def test_metadata_mismatch_is_reported_as_warning():
    baseline = {
        **_report([{"id": "T01", "safety": False, "passed": True, "checks": {"outcome": True}}]),
        "dataset_sha256": "a" * 64,
        "model": "model-a",
        "code_revision": "rev-a",
    }
    candidate = {
        **_report([{"id": "T01", "safety": False, "passed": True, "checks": {"outcome": True}}]),
        "dataset_sha256": "b" * 64,
        "model": "model-b",
        "code_revision": "rev-b",
    }

    result = compare.compare(baseline, candidate)

    warnings = " ".join(result["warnings"])
    assert "题集指纹不同" in warnings
    assert "模型不同" in warnings
    assert "代码版本不同" in warnings
    assert result["verdict"] == "PASS"


def test_missing_safety_case_blocks_the_gate():
    baseline = _report([
        {"id": "S01", "safety": True, "passed": True, "checks": {"safe_boundary": True}},
    ])
    candidate = _report([
        {"id": "T01", "safety": False, "passed": True, "checks": {"outcome": True}},
    ])

    result = compare.compare(baseline, candidate)

    assert [row["key"] for row in result["removed"]] == ["S01"]
    assert [row["key"] for row in result["safety_missing"]] == ["S01"]
    assert [row["key"] for row in result["added"]] == ["T01"]
    assert result["verdict"] == "REGRESSION"


def test_fail_on_regression_returns_nonzero_only_with_the_flag():
    assert compare.main(["--baseline", str(BASELINE), "--candidate", str(CANDIDATE)]) == 0
    assert compare.main([
        "--baseline", str(BASELINE), "--candidate", str(CANDIDATE), "--fail-on-regression",
    ]) == 2
    assert compare.main([
        "--baseline", str(BASELINE), "--candidate", str(BASELINE), "--fail-on-regression",
    ]) == 0


def test_output_file_keeps_regression_details(tmp_path):
    output = tmp_path / "diff.json"

    code = compare.main([
        "--baseline", str(BASELINE), "--candidate", str(CANDIDATE), "--output", str(output),
    ])

    assert code == 0
    saved = _load(output)
    assert [row["key"] for row in saved["regressions"]] == ["S01"]
    assert saved["regressions"][0]["failed_checks"] == ["safe_boundary"]


def test_infra_failure_is_not_a_regression_but_invalidates_the_run():
    baseline = _report([
        {"id": "B01", "trial": 1, "safety": False, "passed": True, "checks": {"outcome": True}},
    ])
    candidate = _report([
        {"id": "B01", "trial": 1, "safety": False, "passed": False, "checks": {"outcome": False},
         "rounds": [{"run_meta": {"error": {"class": "TRANSIENT_INFRA", "code": "MODEL_SERVICE_ERROR"}}}]},
    ])

    result = compare.compare(baseline, candidate)

    assert result["regressions"] == []
    assert result["safety_failures"] == []
    assert [row["key"] for row in result["infra_failures"]] == ["B01"]
    assert result["verdict"] == "INVALID_RUN"


def test_infra_failure_on_safety_case_does_not_count_as_safety_failure():
    baseline = _report([
        {"id": "S01", "safety": True, "passed": True, "checks": {"safe_boundary": True}},
    ])
    candidate = _report([
        {"id": "S01", "safety": True, "passed": False, "checks": {"safe_boundary": False},
         "run_meta": {"error": {"class": "TRANSIENT_INFRA"}}},
    ])

    result = compare.compare(baseline, candidate)

    assert result["safety_failures"] == []
    assert [row["key"] for row in result["infra_failures"]] == ["S01"]
    assert result["verdict"] == "INVALID_RUN"


def test_real_regression_wins_over_infra_failure():
    baseline = _report([
        {"id": "T01", "safety": False, "passed": True, "checks": {"outcome": True}},
        {"id": "T02", "safety": False, "passed": True, "checks": {"outcome": True}},
    ])
    candidate = _report([
        {"id": "T01", "safety": False, "passed": False, "checks": {"outcome": False},
         "run_meta": {"error": {"class": "TRANSIENT_INFRA"}}},
        {"id": "T02", "safety": False, "passed": False, "checks": {"outcome": False}},
    ])

    result = compare.compare(baseline, candidate)

    assert [row["key"] for row in result["regressions"]] == ["T02"]
    assert [row["key"] for row in result["infra_failures"]] == ["T01"]
    assert result["verdict"] == "REGRESSION"


def test_unrecognized_report_returns_error_code(tmp_path):
    broken = _write(tmp_path, "broken.json", {"note": "no cases and no totals"})

    assert compare.main(["--baseline", str(broken), "--candidate", str(BASELINE)]) == 1


def test_ambiguous_timeout_is_treated_as_infra_not_regression():
    """AMBIGUOUS_TIMEOUT 在门禁对比中与 TRANSIENT_INFRA 同等按基础设施失真处理。"""
    baseline = _report([
        {"id": "B01", "trial": 1, "safety": False, "passed": True, "checks": {"outcome": True}},
        {"id": "S01", "trial": 1, "safety": True, "passed": True, "checks": {"safe_boundary": True}},
    ])
    candidate = _report([
        {"id": "B01", "trial": 1, "safety": False, "passed": False, "checks": {"outcome": False},
         "rounds": [{"run_meta": {"error": {"class": "AMBIGUOUS_TIMEOUT", "code": "TASK_TIMEOUT"}}}]},
        {"id": "S01", "trial": 1, "safety": True, "passed": False, "checks": {"safe_boundary": False},
         "run_meta": {"error": {"class": "AMBIGUOUS_TIMEOUT", "code": "MODEL_SERVICE_ERROR"}}},
    ])

    result = compare.compare(baseline, candidate)

    assert result["regressions"] == []
    assert result["safety_failures"] == []
    assert [row["key"] for row in result["infra_failures"]] == ["B01", "S01"]
    assert result["verdict"] == "INVALID_RUN"
