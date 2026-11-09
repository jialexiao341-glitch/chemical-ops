"""运行真实模型评测套件，并可接 prompt 版本门禁；不自动登记基线。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def build_commands(args) -> list[tuple[str, list[str]]]:
    out = args.output_dir
    commands: list[tuple[str, list[str]]] = []
    if args.suite in {"all", "routing"}:
        commands.append(("intent_routing", [
            PYTHON, str(ROOT / "scripts/evaluate_intent_routing.py"),
            "--output", str(out / "intent_routing.json"),
            "--repeats", str(args.routing_repeats),
        ]))
    if args.suite in {"all", "tasks"}:
        commands.append(("agent_tasks", [
            PYTHON, str(ROOT / "scripts/evaluate_agent_tasks.py"),
            "--output", str(out / "agent_tasks.json"),
        ]))
    if args.suite in {"all", "business"}:
        commands.append(("agent_business", [
            PYTHON, str(ROOT / "scripts/evaluate_agent_business.py"),
            "--output", str(out / "agent_business.json"),
            "--repetitions", str(args.business_repetitions),
            "--workers", str(args.business_workers),
        ]))
    cases = ROOT / "docs/evaluation/prod-regression/cases.json"
    if args.suite in {"all", "prod"} and cases.exists():
        commands.append(("prod_regression", [
            PYTHON, str(ROOT / "scripts/evaluate_prod_regression.py"),
            "--cases", str(cases),
            "--output", str(out / "prod_regression.json"),
        ]))
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "routing", "tasks", "business", "prod"), default="all")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "docs/evaluation/candidate", help="候选报告目录")
    parser.add_argument("--routing-repeats", type=int, default=1)
    parser.add_argument("--business-repetitions", type=int, default=1)
    parser.add_argument("--business-workers", type=int, default=3)
    parser.add_argument("--gate", action="store_true", help="评测完成后运行 prompt 版本门禁")
    parser.add_argument("--fail-on-regression", action="store_true", help="门禁发现回归时返回 2")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    args = parser.parse_args(argv)
    if args.routing_repeats < 1 or args.business_repetitions < 1 or args.business_workers < 1:
        parser.error("重复次数和并发数必须为正数")

    commands = build_commands(args)
    if args.dry_run:
        print(json.dumps([{"name": name, "command": command} for name, command in commands],
                         ensure_ascii=False, indent=2))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, command in commands:
        print(f"[eval] {name}: {' '.join(command)}", flush=True)
        code = subprocess.run(command, cwd=ROOT).returncode
        if code != 0:
            failures.append((name, code))
    if failures:
        print("[eval] 失败：" + "、".join(f"{name}={code}" for name, code in failures), file=sys.stderr)
        # 评测脚本在“有用例未通过”时也返回 1；只有报告都没写出来才算运行失败。
        report_files = {
            "intent_routing": "intent_routing.json",
            "agent_tasks": "agent_tasks.json",
            "agent_business": "agent_business.json",
            "prod_regression": "prod_regression.json",
        }
        missing = [name for name, _ in failures
                   if not (args.output_dir / report_files[name]).exists()]
        if missing:
            print("[eval] 未生成报告，无法进入门禁：" + "、".join(missing), file=sys.stderr)
            return 1

    if args.gate:
        gate = [PYTHON, str(ROOT / "scripts/eval_prompt_gate.py"),
                "--candidate-dir", str(args.output_dir)]
        if args.fail_on_regression:
            gate.append("--fail-on-regression")
        return subprocess.run(gate, cwd=ROOT).returncode
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())