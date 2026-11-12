"""envelope 模式门禁：直接消费 eval_harness 产物，与 eval_stability 同一判定口径。"""

import json
from pathlib import Path

import pytest

from scripts import eval_prompt_gate as gate
from scripts import eval_stability as stability


def _envelope(cases, *, model="deepseek-v4.1-flash", repeat=3, suite="tasks"):
    return {"suite": suite, "repeat": repeat, "model": model,
            "code_revision": "rev-1", "prompt_sha256": "sha", "dataset_sha256": "ds",
            "cases": cases}


def _case(key, passes, safety=False, classes=None):
    """passes 是每轮是否通过；classes 是失败轮的错误类别。"""
    trials = []
    for index, passed in enumerate(passes, start=1):
        trials.append({"trial": index, "passed": passed,
                       "error_classes": [] if passed else sorted(classes or []),
                       "failed_checks": [] if passed else ["outcome"]})
    return {"key": key, "safety": safety, "trials": trials}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_envelopes(directory: Path, envelopes: dict) -> None:
    for suite, envelope in envelopes.items():
        _write(directory / f"harness-{suite}.json", envelope)


def _four_envelopes(**overrides) -> dict:
    suites = {suite: _envelope([_case("X01", [True] * 3)], suite=suite)
              for suite in gate.ENVELOPE_SUITES}
    suites.update(overrides)
    return suites


@pytest.fixture(autouse=True)
def _fixed_prompt_versions(monkeypatch):
    monkeypatch.setattr(gate.prompt_registry, "prompt_version",
                        lambda name: f"{name}@1-fixed")


def _with_baseline(tmp_path, envelopes=None) -> Path:
    _write_envelopes(tmp_path / "baselines" / gate.prompt_key(),
                     envelopes or _four_envelopes())
    return tmp_path / "baselines"


def test_envelope_gate_passes_when_candidate_matches_baseline(tmp_path):
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes())

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "PASS"
    assert result["coverage"]["missing"] == []
    assert len(result["reports"]) == 4


def test_envelope_gate_stable_regression_blocks(tmp_path):
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("X01", [False, False, False])])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert row["verdict"] == "REGRESSION"
    assert [item["key"] for item in row["regressions"]] == ["X01"]
    assert result["verdict"] == "REGRESSION"
    code = gate.main(["--candidate-dir", str(candidate),
                      "--baseline-root", str(tmp_path / "baselines"),
                      "--mode", "envelope", "--fail-on-regression"])
    assert code == 2


def test_envelope_gate_single_trial_noise_is_flaky_not_regression(tmp_path):
    """单轮失败不能判回归；稳定性分类与 eval_stability 必须给出同一结论。"""
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("X01", [True, False, True])])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert row["regressions"] == []
    assert [item["key"] for item in row["unstable"]] == ["X01"]
    assert row["verdict"] == "FLAKY"
    assert result["verdict"] == "FLAKY"
    assert stability.classify(2, 3) == "UNSTABLE"


def test_envelope_gate_infra_failure_marks_run_invalid(tmp_path):
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("X01", [False, False, False],
                               classes=["TRANSIENT_INFRA"])])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert row["regressions"] == []
    assert [item["key"] for item in row["infra_failures"]] == ["X01"]
    assert result["verdict"] == "INVALID_RUN"


def test_envelope_gate_excludes_infra_trials_but_marks_run_invalid(tmp_path):
    """单轮模型抖动不算不稳定，但批次仍不可作基线证据。"""
    _with_baseline(tmp_path, _four_envelopes(
        tasks=_envelope([_case("X01", [True] * 3)])))
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("X01", [True, False, True], classes=["TRANSIENT_INFRA"])])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert row["regressions"] == []
    assert row["unstable"] == []
    assert [item["key"] for item in row["infra_failures"]] == ["X01"]
    assert result["verdict"] == "INVALID_RUN"


def test_envelope_gate_requires_all_four_suites(tmp_path):
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, {"tasks": _four_envelopes()["tasks"]})

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "NOT_RUN"
    assert result["coverage"]["present"] == ["tasks"]
    assert set(result["coverage"]["missing"]) == {"routing", "business", "prod"}


def test_envelope_gate_blocks_cross_model_comparison(tmp_path):
    _with_baseline(tmp_path)
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("X01", [True] * 3)], model="other-model")))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "INVALID_RUN"
    assert result["meta_mismatches"] == [{
        "suite": "tasks", "field": "model",
        "baseline": "deepseek-v4.1-flash", "candidate": "other-model"}]


def test_envelope_gate_counts_failed_safety_case_as_regression(tmp_path):
    _with_baseline(tmp_path, _four_envelopes(
        tasks=_envelope([_case("T08", [True] * 3, safety=True)])))
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("T08", [True, False, True], safety=True)])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert [item["key"] for item in row["safety_failures"]] == ["T08"]
    assert result["verdict"] == "REGRESSION"


def test_envelope_gate_blocks_safety_case_with_statistical_majority(tmp_path):
    """安全用例零容忍：19/20 仍被 Wilson 判 STABLE_PASS，也必须拦。"""
    _with_baseline(tmp_path, _four_envelopes(
        tasks=_envelope([_case("T11", [True] * 20, safety=True)])))
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes(
        tasks=_envelope([_case("T11", [True] * 19 + [False], safety=True)])))

    result = gate.run_envelope_gate(candidate, tmp_path / "baselines")
    row = next(row for row in result["reports"] if row["name"] == "tasks")

    assert stability.classify(19, 20) == "STABLE_PASS"
    assert [item["key"] for item in row["safety_failures"]] == ["T11"]
    assert result["verdict"] == "REGRESSION"


def test_envelope_gate_rejects_missing_baseline(tmp_path):
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes())

    with pytest.raises(ValueError, match="基线 envelope"):
        gate.run_envelope_gate(candidate, tmp_path / "baselines")


def test_promote_copies_envelopes_and_records_meta(tmp_path):
    candidate = tmp_path / "candidate"
    _write_envelopes(candidate, _four_envelopes())

    result = gate.promote_baseline(candidate, tmp_path / "baselines")

    target = tmp_path / "baselines" / result["prompt_key"]
    assert result["files"] == []
    assert set(result["envelopes"]) == set(gate.ENVELOPE_FILES)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["envelope_meta"]["harness-tasks.json"]["model"] == "deepseek-v4.1-flash"
    assert (target / "harness-tasks.json").exists()


def test_promote_envelopes_preserves_existing_raw_baseline(tmp_path):
    """只登记 envelope 时，既有原始报告与版本元数据不能被抹掉。"""
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", {"cases": [{"id": "T01", "passed": True, "run_meta": {
        "prompt_versions": {"routing": "routing@1-fixed", "planner": "planner@1-fixed"}}}]})
    gate.promote_baseline(candidate, tmp_path / "baselines")
    manifest_path = tmp_path / "baselines" / gate.prompt_key() / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["collected_model"] = {"name": "MaxApi"}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    envelopes = tmp_path / "candidate-envelopes"
    _write_envelopes(envelopes, _four_envelopes())
    result = gate.promote_baseline(envelopes, tmp_path / "baselines", force=True)

    assert result["files"] == ["agent_tasks.json"]
    assert result["report_versions"]["agent_tasks.json"]["planner"] == ["planner@1-fixed"]
    assert set(result["envelopes"]) == set(gate.ENVELOPE_FILES)
    merged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert merged["collected_model"] == {"name": "MaxApi"}
    assert merged["coverage"]["missing"] == [
        "intent_routing.json", "agent_business.json", "prod_regression.json"]


def test_envelope_mode_rejects_retest_attempts(tmp_path):
    code = gate.main(["--candidate-dir", str(tmp_path / "candidate"),
                      "--baseline-root", str(tmp_path / "baselines"),
                      "--mode", "envelope", "--retest-attempts", "3"])

    assert code == 1