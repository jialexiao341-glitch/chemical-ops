"""Prompt 版本评测门禁：基线缺失、回归与显式登记。"""

import json
from pathlib import Path

import pytest

from scripts import eval_prompt_gate as gate


def _report(passed: bool) -> dict:
    return {"cases": [{"id": "T01", "passed": passed, "checks": {"outcome": passed}}]}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_all(directory: Path, passed: bool = True) -> None:
    """门禁要求四份报告齐全；子集目录只能判 NOT_RUN。"""
    for filename in gate.REPORT_FILES.values():
        _write(directory / filename, _report(passed))


@pytest.fixture(autouse=True)
def _fixed_prompt_versions(monkeypatch):
    monkeypatch.setattr(gate.prompt_registry, "prompt_version",
                        lambda name: f"{name}@1-fixed")


def test_gate_requires_current_prompt_baseline(tmp_path):
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", _report(True))

    with pytest.raises(ValueError, match="缺少当前 prompt 版本"):
        gate.run_gate(candidate, tmp_path / "baselines")


def test_gate_passes_when_candidate_matches_baseline(tmp_path):
    key = gate.prompt_key()
    baseline = tmp_path / "baselines" / key
    candidate = tmp_path / "candidate"
    _write_all(baseline)
    _write_all(candidate)

    result = gate.run_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "PASS"
    assert result["prompt_key"] == key
    assert result["coverage"]["missing"] == []
    assert len(result["reports"]) == 4
    assert result["reports"][0]["regressions"] == []


def test_gate_rejects_subset_report_as_not_run(tmp_path):
    key = gate.prompt_key()
    _write_all(tmp_path / "baselines" / key)
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", _report(True))

    result = gate.run_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "NOT_RUN"
    assert result["coverage"]["present"] == ["agent_tasks"]
    assert set(result["coverage"]["missing"]) == {"intent_routing", "agent_business", "prod_regression"}
    code = gate.main(["--candidate-dir", str(candidate),
                      "--baseline-root", str(tmp_path / "baselines"),
                      "--fail-on-regression"])
    assert code == 2


def test_gate_detects_regression_and_cli_exit_code(tmp_path):
    key = gate.prompt_key()
    baseline = tmp_path / "baselines" / key
    candidate = tmp_path / "candidate"
    _write_all(baseline)
    _write_all(candidate)
    _write(candidate / "agent_tasks.json", _report(False))

    result = gate.run_gate(candidate, tmp_path / "baselines")
    assert result["verdict"] == "REGRESSION"
    tasks = next(row for row in result["reports"] if row["name"] == "agent_tasks")
    assert tasks["regressions"] == ["T01"]

    code = gate.main(["--candidate-dir", str(candidate),
                      "--baseline-root", str(tmp_path / "baselines"),
                      "--fail-on-regression"])
    assert code == 2


def test_promote_baseline_copies_reports_and_manifest(tmp_path):
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", _report(True))

    result = gate.promote_baseline(candidate, tmp_path / "baselines")

    target = tmp_path / "baselines" / result["prompt_key"]
    assert (target / "agent_tasks.json").exists()
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["prompt_key"] == result["prompt_key"]
    assert manifest["files"] == ["agent_tasks.json"]
    assert manifest["coverage"]["missing"] == ["intent_routing.json", "agent_business.json", "prod_regression.json"]


def test_promote_records_versions_and_carried_forward_reports(tmp_path):
    candidate = tmp_path / "candidate"
    report = {"cases": [{"id": "B01", "passed": True, "rounds": [{
        "run_meta": {"prompt_versions": {
            "routing": "routing@1-old", "planner": "planner@1-fixed"}}}]}]}
    _write(candidate / "agent_business.json", report)

    result = gate.promote_baseline(candidate, tmp_path / "baselines")

    assert result["report_versions"]["agent_business.json"] == {
        "planner": ["planner@1-fixed"], "routing": ["routing@1-old"]}
    assert result["carried_forward"] == [{
        "file": "agent_business.json", "versions": {"routing": ["routing@1-old"]}}]
    manifest = json.loads(
        (tmp_path / "baselines" / result["prompt_key"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["carried_forward"] == result["carried_forward"]


def test_promote_marks_current_version_reports_as_not_carried(tmp_path):
    candidate = tmp_path / "candidate"
    report = {"prompt_versions": {"routing": "routing@1-fixed", "planner": "planner@1-fixed"},
              "cases": [{"id": "PR-1", "passed": True}]}
    _write(candidate / "prod_regression.json", report)

    result = gate.promote_baseline(candidate, tmp_path / "baselines")

    assert result["carried_forward"] == []


def test_promote_requires_force_to_overwrite(tmp_path):
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", _report(True))
    gate.promote_baseline(candidate, tmp_path / "baselines")

    with pytest.raises(ValueError, match="覆盖需 --force"):
        gate.promote_baseline(candidate, tmp_path / "baselines")