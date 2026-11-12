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
    assert business[business.index("--scratch-dir") + 1].endswith(".scratch")


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


def test_stability_excludes_infra_trials_from_denominator():
    case = {"key": "T10", "trials": [
        {"passed": True},
        {"passed": False, "error_classes": ["TRANSIENT_INFRA"]},
        {"passed": True},
    ]}

    passed, total, excluded, verdict = stability.classify_case(case)

    assert (passed, total, excluded) == (2, 2, 1)
    assert verdict == "STABLE_PASS"


def test_stability_with_only_infra_trials_is_no_evidence():
    case = {"key": "T11", "trials": [
        {"passed": False, "error_classes": ["TRANSIENT_INFRA"]}]}

    _, total, excluded, verdict = stability.classify_case(case)

    assert (total, excluded, verdict) == (0, 1, stability.NO_EVIDENCE)
    assert stability.classify(0, 0) == stability.NO_EVIDENCE


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


def test_merge_keeps_safety_flag_and_failed_checks():
    reports = [_report([
        {"id": "T08", "passed": False, "safety": True,
         "checks": {"outcome": False, "refusal_safety": True}},
        {"id": "T01", "passed": True, "safety": False},
    ])]

    envelope = harness.merge_trials("tasks", reports, 1)
    by_key = {case["key"]: case for case in envelope["cases"]}

    assert by_key["T08"]["safety"] is True
    assert by_key["T01"]["safety"] is False
    assert by_key["T08"]["trials"][0]["failed_checks"] == ["outcome"]


def test_run_all_writes_one_envelope_per_suite(tmp_path):
    calls = []

    def runner(command, path):
        calls.append(path.name)
        return _report([{"id": "X01", "passed": True}])

    envelopes = harness.run_all(tmp_path, repeat=1, runner=runner)

    assert set(envelopes) == set(harness.SUITES)
    assert (tmp_path / "harness-routing.json").exists()
    assert (tmp_path / "harness-prod.json").exists()
    assert len(calls) == len(harness.SUITES)
    assert harness.worst_verdict(["PASS", "INVALID_RUN"]) == "INVALID_RUN"
    assert harness.worst_verdict(["PASS", "FAILURES", "INVALID_RUN"]) == "FAILURES"
    assert harness.worst_verdict(["PASS", "PASS"]) == "PASS"


def _infra_report() -> dict:
    return _report([
        {"id": "T01", "passed": False, "rounds": [
            {"run_meta": {"error": {"class": "TRANSIENT_INFRA", "code": "INTENT_SERVICE_ERROR"}}}]},
    ])


def _write_trial(out: Path, index: int, data: dict) -> None:
    path = harness.trial_path(out, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_resume_reruns_infra_contaminated_trial(tmp_path):
    out = tmp_path / "envelope.json"
    _write_trial(out, 1, _report([{"id": "T01", "passed": True}]))
    _write_trial(out, 2, _infra_report())
    rerun = []

    def runner(command, path):
        rerun.append(path.name)
        return _report([{"id": "T01", "passed": True}])

    envelope = harness.run("tasks", out, repeat=2, resume=True, runner=runner)

    assert rerun == ["envelope.trial-2.json"]
    assert envelope["summary"]["verdict"] == "PASS"


def test_resume_reuse_infra_keeps_contaminated_trial(tmp_path):
    out = tmp_path / "envelope.json"
    _write_trial(out, 1, _infra_report())

    def runner(_command, _path):
        raise AssertionError("不应重跑")

    envelope = harness.run("tasks", out, repeat=1, resume=True,
                           reuse_infra=True, runner=runner)

    assert envelope["summary"]["verdict"] == "INVALID_RUN"


def test_refresh_trial_overwrites_contaminated_report(tmp_path):
    """污染轮次重跑时必须覆盖旧报告，否则合并仍会读回脏数据。"""
    out = tmp_path / "envelope.json"
    _write_trial(out, 1, _infra_report())

    def runner(command, path):
        path.write_text(json.dumps(_report([{"id": "T01", "passed": True}])), encoding="utf-8")
        return _report([{"id": "T01", "passed": True}])

    envelope = harness.run("tasks", out, repeat=1, resume=True, runner=runner)

    assert envelope["summary"]["verdict"] == "PASS"
    assert json.loads(harness.trial_path(out, 1).read_text(encoding="utf-8"))["cases"][0]["passed"]