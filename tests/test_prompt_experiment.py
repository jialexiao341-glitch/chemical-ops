"""Prompt 变体实验：配对列联表、McNemar 精确检验与跨模型阻断。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import prompt_experiment as experiment


def _case(key: str, passes: list[bool], classes: list[str] | None = None) -> dict:
    return {"key": key, "safety": False, "trials": [
        {"trial": index, "passed": passed,
         "error_classes": [] if passed else sorted(classes or []),
         "failed_checks": [] if passed else ["outcome"]}
        for index, passed in enumerate(passes, start=1)]}


def _envelope(cases: list[dict], *, suite: str = "tasks", model: str = "deepseek-v4.1-flash",
              dataset: str = "ds") -> dict:
    return {"suite": suite, "model": model, "dataset_sha256": dataset, "repeat": 3, "cases": cases}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _dir(tmp_path: Path, name: str, envelopes: dict[str, dict]) -> Path:
    directory = tmp_path / name
    for suite, envelope in envelopes.items():
        _write(directory / f"harness-{suite}.json", envelope)
    return directory


def test_mcnemar_exact_matches_binomial_tail():
    assert experiment.mcnemar_exact(0, 10) == pytest.approx(2 / 1024)
    assert experiment.mcnemar_exact(2, 2) == 1.0
    assert experiment.mcnemar_exact(0, 0) == 1.0
    assert experiment.mcnemar_exact(6, 0) == pytest.approx(2 / 64)


def test_improvements_across_six_cases_are_significant(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope(
        [_case(f"T{i}", [False, False, False]) for i in range(6)])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case(f"T{i}", [True, True, True]) for i in range(6)])})

    result = experiment.run(baseline, candidate)
    row = result["suites"][0]

    assert (row["candidate_only"], row["baseline_only"]) == (6, 0)
    assert row["mcnemar_p"] == pytest.approx(2 / 64)
    assert row["verdict"] == "IMPROVED"
    assert result["verdict"] == "IMPROVED"


def test_degradations_are_reported_per_case(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope(
        [_case(f"T{i}", [True, True, True]) for i in range(6)])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case(f"T{i}", [True, False, False]) for i in range(6)])})

    result = experiment.run(baseline, candidate)
    row = result["suites"][0]

    assert row["baseline_only"] == 6
    assert [item["key"] for item in row["degraded"]] == [f"T{i}" for i in range(6)]
    assert row["verdict"] == "DEGRADED"


def test_small_discordant_pairs_stay_inconclusive(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope(
        [_case("T1", [False, False, False]), _case("T2", [True, True, True])])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case("T1", [True, True, True]), _case("T2", [False, False, False])])})

    row = experiment.run(baseline, candidate)["suites"][0]

    assert row["mcnemar_p"] == 1.0
    assert row["verdict"] == "INCONCLUSIVE"


def test_infra_trials_are_excluded_from_pairing(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope([_case("T1", [True, True])])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case("T1", [True, False], classes=["TRANSIENT_INFRA"])])})

    row = experiment.run(baseline, candidate)["suites"][0]

    assert row["cases"] == 1
    assert row["baseline_only"] == 0
    assert row["candidate_only"] == 0
    assert row["verdict"] == "INCONCLUSIVE"


def test_case_without_valid_trials_is_listed_not_scored(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope([_case("T1", [True, True])])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case("T1", [False], classes=["TRANSIENT_INFRA"])])})

    row = experiment.run(baseline, candidate)["suites"][0]

    assert row["cases"] == 0
    assert [item["key"] for item in row["excluded"]] == ["T1"]
    assert row["verdict"] == "NO_EVIDENCE"


def test_cross_model_comparison_is_invalid(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope([_case("T1", [True])])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope(
        [_case("T1", [True])], model="other-model")})

    result = experiment.run(baseline, candidate)

    assert result["verdict"] == "INVALID"
    assert result["model_mismatch"] == ["tasks"]
    code = experiment.main(["--baseline-dir", str(baseline),
                            "--candidate-dir", str(candidate)])
    assert code == 2


def test_missing_common_suite_raises(tmp_path):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope([_case("T1", [True])])})
    candidate = _dir(tmp_path, "candidate", {"routing": _envelope([_case("Q1", [True])])})

    with pytest.raises(ValueError, match="没有可比对"):
        experiment.run(baseline, candidate)


def test_cli_writes_markdown_report(tmp_path, capsys):
    baseline = _dir(tmp_path, "baseline", {"tasks": _envelope([_case("T1", [True])])})
    candidate = _dir(tmp_path, "candidate", {"tasks": _envelope([_case("T1", [True])])})
    out = tmp_path / "report.md"

    code = experiment.main(["--baseline-dir", str(baseline),
                            "--candidate-dir", str(candidate), "--out", str(out)])

    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "McNemar" in text and "INCONCLUSIVE" in text
    assert "不写基线" in capsys.readouterr().out