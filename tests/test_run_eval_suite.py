"""评测套件编排：命令构造与 dry-run 不触发模型调用。"""

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_eval_suite


def _args(tmp_path: Path, suite: str = "all"):
    return SimpleNamespace(
        suite=suite, output_dir=tmp_path,
        routing_repeats=2, business_repetitions=1, business_workers=3,
    )


def test_build_commands_covers_four_reports(tmp_path):
    commands = run_eval_suite.build_commands(_args(tmp_path))

    assert [name for name, _ in commands] == [
        "intent_routing", "agent_tasks", "agent_business", "prod_regression"]
    assert str(tmp_path / "intent_routing.json") in commands[0][1]
    assert "--repeats" in commands[0][1] and "2" in commands[0][1]
    assert str(tmp_path / "agent_business.json") in commands[2][1]
    assert "--repetitions" in commands[2][1]
    assert str(tmp_path / "agent_business.scratch") in commands[2][1]
    assert str(tmp_path / "prod_regression.json") in commands[3][1]


def test_gate_still_runs_when_eval_cases_fail(tmp_path, monkeypatch):
    """评测脚本以 1 退出但报告存在时，应继续做基线对比而不是直接失败。"""
    (tmp_path / "agent_tasks.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_eval_suite, "build_commands",
                        lambda _args: [("agent_tasks", ["evaluate"])])
    calls = []

    def fake_run(command, cwd):
        calls.append(command)
        return SimpleNamespace(returncode=1 if command[0] == "evaluate" else 0)

    monkeypatch.setattr(run_eval_suite.subprocess, "run", fake_run)

    code = run_eval_suite.main(["--gate", "--output-dir", str(tmp_path)])

    assert code == 0
    assert calls[0] == ["evaluate"]
    assert calls[1][1].endswith("eval_prompt_gate.py")


def test_dry_run_prints_commands_without_execution(tmp_path, capsys):
    code = run_eval_suite.main(["--dry-run", "--suite", "routing",
                                "--output-dir", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["name"] == "intent_routing"
    assert payload[0]["command"][1].endswith("evaluate_intent_routing.py")


def test_harness_dry_run_prints_envelope_command(tmp_path, capsys):
    code = run_eval_suite.main(["--dry-run", "--harness", "--suite", "all",
                                "--repeat", "3", "--output-dir", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    command = payload[0]["command"]
    assert payload[0]["name"] == "harness"
    assert command[1].endswith("eval_harness.py")
    assert command[command.index("--repeat") + 1] == "3"
    assert command[command.index("--out-dir") + 1] == str(
        tmp_path / run_eval_suite.ENVELOPE_SUBDIR)


def test_harness_mode_runs_gate_on_envelopes(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, cwd):
        calls.append(command)
        joined = " ".join(command)
        if "eval_harness.py" in joined:
            envelope_dir = tmp_path / run_eval_suite.ENVELOPE_SUBDIR
            envelope_dir.mkdir(parents=True, exist_ok=True)
            for name in run_eval_suite.ENVELOPE_FILES.values():
                (envelope_dir / name).write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_eval_suite.subprocess, "run", fake_run)

    code = run_eval_suite.main(["--harness", "--gate", "--repeat", "3",
                                "--output-dir", str(tmp_path)])

    assert code == 0
    gate_command = calls[1]
    assert gate_command[1].endswith("eval_prompt_gate.py")
    assert gate_command[gate_command.index("--mode") + 1] == "envelope"


def test_harness_mode_reports_missing_envelopes(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval_suite.subprocess, "run",
                        lambda command, cwd: SimpleNamespace(returncode=0))

    code = run_eval_suite.main(["--harness", "--gate", "--output-dir", str(tmp_path)])

    assert code == 1


def _pin_prompt_key(monkeypatch, key: str = "routing@test__planner@test"):
    from scripts import eval_prompt_gate

    monkeypatch.setattr(eval_prompt_gate, "prompt_key", lambda: key)
    return key


def test_require_baseline_fails_before_any_sampling(tmp_path, monkeypatch, capsys):
    """CI 在花几十分钟采样前就要发现缺基线，而不是跑完才报无法判定。"""
    key = _pin_prompt_key(monkeypatch)
    called = []
    monkeypatch.setattr(run_eval_suite.subprocess, "run",
                        lambda command, cwd: called.append(command))

    code = run_eval_suite.main(["--harness", "--require-baseline",
                                "--baseline-root", str(tmp_path / "baselines"),
                                "--output-dir", str(tmp_path / "out")])

    assert code == 1
    assert called == []
    stderr = capsys.readouterr().err
    assert key in stderr
    assert "harness-routing.json" in stderr


def test_require_baseline_accepts_complete_envelope_baseline(tmp_path, monkeypatch):
    key = _pin_prompt_key(monkeypatch)
    baseline_dir = tmp_path / "baselines" / key
    baseline_dir.mkdir(parents=True)
    for name in run_eval_suite.ENVELOPE_FILES.values():
        (baseline_dir / name).write_text("{}", encoding="utf-8")

    calls = []

    def fake_run(command, cwd):
        calls.append(command)
        joined = " ".join(command)
        if "eval_harness.py" in joined:
            envelope_dir = tmp_path / "out" / run_eval_suite.ENVELOPE_SUBDIR
            envelope_dir.mkdir(parents=True, exist_ok=True)
            for name in run_eval_suite.ENVELOPE_FILES.values():
                (envelope_dir / name).write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_eval_suite.subprocess, "run", fake_run)

    code = run_eval_suite.main(["--harness", "--require-baseline",
                                "--baseline-root", str(tmp_path / "baselines"),
                                "--output-dir", str(tmp_path / "out"),
                                "--gate", "--fail-on-regression"])

    assert code == 0
    assert "eval_harness.py" in " ".join(calls[0])
    assert calls[1][1].endswith("eval_prompt_gate.py")
    assert "--fail-on-regression" in calls[1]


def test_require_baseline_rejected_outside_harness_mode(tmp_path):
    try:
        run_eval_suite.main(["--require-baseline", "--output-dir", str(tmp_path)])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse 以 SystemExit 结束
        raise AssertionError("--require-baseline 未配合 --harness 时应拒绝执行")