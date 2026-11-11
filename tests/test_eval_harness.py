"""统一评测 harness 与稳定性判定：合并、分类、断点续跑与 Wilson 区间。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import eval_harness as harness
from scripts import eval_stability as stability


def _report(cases: list[dict]) -> dict:
    return {"model": "deepseek-v4.1-flash", "code_revision": "rev-1", "cases": cases}


def test_merge_keeps_every_trial_and_counts_case_as_failed():
    reports = [
        _report([{"id": "T01", "passed": True}, {"id": "T02", "passed": False}]),
        _report([{"id": "T01", "passed": True}, {"id": "T02", "passed": True}]),
    ]

    envelope = harness.merge_trials("tasks", reports, 2)

    by_key = {case["key"]: case for case in envelope["cases"]}
    assert len(by_key["T01"]["trials"]) == 2
    assert [trial["passed"] for trial in by_key["T02"]["trials"]] == [False, True]
    assert envelope["summary"] == {"total": 2, "passed": 1, "failed": 1,
                                   "infra_failed": 0, "verdict": "FAILURES"}
    assert envelope["model"] == "deepseek-v4.1-flash"


def test_infra_only_failures_mark_run_invalid():
    reports = [_report([
        {"id": "B01", "passed": False, "rounds": [
            {"run_meta": {"error": {"class": "TRANSIENT_INFRA"}}}]},
        {"id": "B02", "passed": True},
    ])]

    envelope = harness.merge_trials("business", reports, 1)

    assert envelope["summary"]["verdict"] == "INVALID_RUN"
    assert envelope["summary"]["infra_failed"] == 1


def test_mixed_infra_and_real_failure_is_failures():
    reports = [_report([
        {"id": "B01", "passed": False, "rounds": [
            {"run_meta": {"error": {"class": "TRANSIENT_INFRA"}}}]},
        {"id": "B02", "passed": False, "checks": {"outcome": False}},
    ])]

    envelope = harness.merge_trials("business", reports, 1)

    assert envelope["summary"]["verdict"] == "FAILURES"
    assert envelope["summary"]["infra_failed"] == 1


def test_resume_reuses_existing_trial_files(tmp_path):
    out = tmp_path / "envelope.json"
    first = harness.trial_path(out, 1)
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text(json.dumps(_report([{"id": "T01", "passed": True}])), encoding="utf-8")
    calls = []

    def runner(command, path):
        calls.append((command, path))
        return _report([{"id": "T01", "passed": True}])

    envelope = harness.run("tasks", out, repeat=2, resume=True, runner=runner)

    assert len(calls) == 1  # 只补第二轮
    assert envelope["repeat"] == 2
    assert envelope["summary"]["verdict"] == "PASS"


def test_build_command_passes_only_suite_specific_flags():
    routing = harness.build_command("routing", Path("r.json"), workers=2)
    business = harness.build_command("business", Path("b.json"), workers=3)

    assert routing[1].endswith("evaluate_intent_routing.py")
    assert routing[routing.index("--repeats") + 1] == "1"
    assert business[business.index("--workers") + 1] == "3"
    assert business[business.index("--repetitions") + 1] == "1"


def test_wilson_bounds_and_classification():
    low, high = stability.wilson(9, 10)
    assert 0.5 < low < 0.9 and 0.95 < high <= 1.0
    assert stability.wilson(0, 0) == (0.0, 1.0)

    assert stability.classify(10, 10) == "STABLE_PASS"
    assert stability.classify(0, 10) == "STABLE_FAIL"
    assert stability.classify(5, 10) == "UNSTABLE"
    assert stability.classify(2, 3) == "UNSTABLE"
    assert stability.classify(3, 3) == "STABLE_PASS"


def test_stability_report_flags_unstable_case(tmp_path):
    envelope = {
        "suite": "tasks",
        "cases": [
            {"key": "T01", "trials": [{"passed": True}] * 3},
            {"key": "T04", "trials": [{"passed": True}, {"passed": False}, {"passed": True}]},
        ],
    }
    path = tmp_path / "env.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    code = stability.main(["--envelope", str(path), "--out", str(tmp_path / "s.md")])

    assert code == 2
    text = (tmp_path / "s.md").read_text(encoding="utf-8")
    assert "T04" in text and "UNSTABLE" in text


def test_load_envelopes_merges_trials_for_same_key(tmp_path):
    one = tmp_path / "a.json"
    two = tmp_path / "b.json"
    one.write_text(json.dumps({"model": "m", "cases": [
        {"key": "T01", "trials": [{"passed": True}]}]}), encoding="utf-8")
    two.write_text(json.dumps({"cases": [
        {"key": "T01", "trials": [{"passed": False}]}]}), encoding="utf-8")

    merged = stability.load_envelopes([one, two])

    assert merged["model"] == "m"
    assert len(merged["cases"][0]["trials"]) == 2