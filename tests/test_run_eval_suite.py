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


def test_build_commands_covers_three_reports(tmp_path):
    commands = run_eval_suite.build_commands(_args(tmp_path))

    assert [name for name, _ in commands] == ["intent_routing", "agent_tasks", "agent_business"]
    assert str(tmp_path / "intent_routing.json") in commands[0][1]
    assert "--repeats" in commands[0][1] and "2" in commands[0][1]
    assert str(tmp_path / "agent_business.json") in commands[2][1]
    assert "--repetitions" in commands[2][1]


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