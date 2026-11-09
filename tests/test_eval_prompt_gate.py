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
    _write(baseline / "agent_tasks.json", _report(True))
    _write(candidate / "agent_tasks.json", _report(True))

    result = gate.run_gate(candidate, tmp_path / "baselines")

    assert result["verdict"] == "PASS"
    assert result["prompt_key"] == key
    assert result["reports"][0]["regressions"] == []


def test_gate_detects_regression_and_cli_exit_code(tmp_path):
    key = gate.prompt_key()
    baseline = tmp_path / "baselines" / key
    candidate = tmp_path / "candidate"
    _write(baseline / "agent_tasks.json", _report(True))
    _write(candidate / "agent_tasks.json", _report(False))

    result = gate.run_gate(candidate, tmp_path / "baselines")
    assert result["verdict"] == "REGRESSION"
    assert result["reports"][0]["regressions"] == ["T01"]

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


def test_promote_requires_force_to_overwrite(tmp_path):
    candidate = tmp_path / "candidate"
    _write(candidate / "agent_tasks.json", _report(True))
    gate.promote_baseline(candidate, tmp_path / "baselines")

    with pytest.raises(ValueError, match="覆盖需 --force"):
        gate.promote_baseline(candidate, tmp_path / "baselines")