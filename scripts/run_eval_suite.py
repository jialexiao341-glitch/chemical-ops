"""运行真实模型评测套件，并可接 prompt 版本门禁；不自动登记基线。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
# 直接执行脚本时 sys.path[0] 是 scripts/，需补上仓库根才能导入 scripts.* 与 backend.app。
sys.path.insert(0, str(ROOT))

PREFLIGHT_PROMPT = "回复 OK"
PREFLIGHT_TIMEOUT = 30.0

# 与 eval_harness / eval_prompt_gate 共用同一命名：envelope 落到候选目录的 envelopes/ 子目录，
# 与原始报告分开放置，门禁按名直读。
ENVELOPE_SUBDIR = "envelopes"
ENVELOPE_FILES = {suite: f"harness-{suite}.json"
                  for suite in ("routing", "tasks", "business", "prod")}
BASELINE_ROOT = ROOT / "docs/evaluation/baselines"


def baseline_probe(baseline_root: Path, suite: str) -> dict:
    """按当前 prompt 版本查 envelope 基线；CI 在花 90 分钟采样前先用它快速失败。

    目录与命名必须和 eval_prompt_gate.run_envelope_gate 一致，否则会出现“门禁找不到基线”
    与“基线检查通过”两套判断。
    """
    from scripts import eval_prompt_gate  # 延迟导入：dry-run 与命令构造不需要模型/后端依赖

    key = eval_prompt_gate.prompt_key()
    suites = tuple(ENVELOPE_FILES) if suite == "all" else (suite,)
    directory = baseline_root / key
    missing = [name for name in suites if not (directory / ENVELOPE_FILES[name]).exists()]
    return {"prompt_key": key, "baseline_dir": str(directory), "missing": missing,
            "required": list(suites)}


def require_baseline(baseline_root: Path, suite: str) -> dict:
    """当前 prompt 版本没有完整 envelope 基线时直接报错，避免采样后才发现无法判定。"""
    probe = baseline_probe(baseline_root, suite)
    if probe["missing"]:
        raise ValueError(
            f"当前 prompt 版本 {probe['prompt_key']} 缺少 envelope 基线："
            f"{'、'.join(ENVELOPE_FILES[name] for name in probe['missing'])}"
            f"（目录 {probe['baseline_dir']}）；"
            "请先审阅候选 envelope 并执行 eval_prompt_gate.py --promote-baseline")
    return probe


def preflight_model() -> tuple[bool, str]:
    """跑评测前用一次最小请求确认模型服务可用，避免跑到一半才因掉线整轮作废。"""

    sys.path.insert(0, str(ROOT / "backend"))
    import httpx  # noqa: PLC0415

    from app.core.config import get_settings  # noqa: PLC0415
    from app.modules.ai_agent.model_access import model_catalog  # noqa: PLC0415
    from app.modules.ai_agent.model_access.gateway import resolve_model_profile  # noqa: PLC0415

    model_catalog.activate()
    profile = resolve_model_profile(get_settings())
    url = f"{profile.base_url.rstrip('/')}/chat/completions"
    payload = {"model": profile.model, "messages": [{"role": "user", "content": PREFLIGHT_PROMPT}],
               "temperature": 0, "max_tokens": 16, "stream": False}
    try:
        response = httpx.post(url, headers={"Authorization": f"Bearer {profile.api_key}",
                                            "Content-Type": "application/json"},
                              json=payload, timeout=PREFLIGHT_TIMEOUT)
    except httpx.HTTPError as exc:
        return False, f"{profile.name}（{profile.model}）连接失败：{type(exc).__name__}"
    if response.status_code != 200:
        return False, f"{profile.name}（{profile.model}）返回 HTTP {response.status_code}"
    try:
        choices = response.json().get("choices")
    except ValueError:
        return False, f"{profile.name}（{profile.model}）返回非 JSON 响应"
    if not isinstance(choices, list) or not choices:
        return False, f"{profile.name}（{profile.model}）响应缺少 choices"
    return True, f"{profile.name}（{profile.model}）可用"


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
            "--scratch-dir", str(out / "agent_business.scratch"),
        ]))
    cases = ROOT / "docs/evaluation/prod-regression/cases.json"
    if args.suite in {"all", "prod"} and cases.exists():
        commands.append(("prod_regression", [
            PYTHON, str(ROOT / "scripts/evaluate_prod_regression.py"),
            "--cases", str(cases),
            "--output", str(out / "prod_regression.json"),
        ]))
    return commands


def build_harness_command(args) -> list[str]:
    """多轮采样走 eval_harness：四套件 × N 轮，输出 envelope 供门禁直连。"""
    return [PYTHON, str(ROOT / "scripts/eval_harness.py"),
            "--suite", args.suite,
            "--out-dir", str(args.output_dir / ENVELOPE_SUBDIR),
            "--repeat", str(args.repeat), "--workers", str(args.business_workers)]


def missing_envelopes(directory: Path, suite: str) -> list[str]:
    """缺哪套件的 envelope 就报哪套件；不能拿子集进 envelope 门禁。"""
    suites = tuple(ENVELOPE_FILES) if suite == "all" else (suite,)
    return [name for name in suites if not (directory / ENVELOPE_FILES[name]).exists()]


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
    parser.add_argument("--retest-attempts", type=int, default=0,
                        help="门禁判回归时按编号重跑复核（≥3），用于区分采样波动与稳定回归")
    parser.add_argument("--harness", action="store_true",
                        help="走 eval_harness 多轮采样，输出 harness-<suite>.json envelope")
    parser.add_argument("--repeat", type=int, default=1, help="harness 模式下每个套件的采样轮次")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    parser.add_argument("--preflight", action="store_true",
                        help="先用一次最小模型请求确认服务可用，不可用时不发起批量评测")
    parser.add_argument("--baseline-root", type=Path, default=BASELINE_ROOT,
                        help="envelope 基线根目录；默认 docs/evaluation/baselines")
    parser.add_argument("--require-baseline", action="store_true",
                        help="harness 采样前校验当前 prompt 版本有完整 envelope 基线，缺失即退出")
    args = parser.parse_args(argv)
    if args.routing_repeats < 1 or args.business_repetitions < 1 or args.business_workers < 1:
        parser.error("重复次数和并发数必须为正数")
    if args.repeat < 1:
        parser.error("采样轮次必须为正数")
    if args.require_baseline and not args.harness:
        parser.error("--require-baseline 只适用于 --harness：基线以 envelope 为判定口径")

    if args.harness:
        if args.require_baseline:
            try:
                probe = require_baseline(args.baseline_root, args.suite)
            except ValueError as exc:
                print(f"[eval] {exc}", file=sys.stderr)
                return 1
            print(f"[baseline] 基线齐全：{probe['prompt_key']}（{probe['baseline_dir']}）",
                  flush=True)
        command = build_harness_command(args)
        if args.dry_run:
            print(json.dumps([{"name": "harness", "command": command}],
                             ensure_ascii=False, indent=2))
            return 0
        if args.preflight:
            ok, detail = preflight_model()
            print(f"[preflight] {'OK' if ok else 'FAIL'}：{detail}", flush=True)
            if not ok:
                print("[preflight] 模型服务不可用，已取消本轮评测", file=sys.stderr)
                return 1
        args.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[eval] harness: {' '.join(command)}", flush=True)
        code = subprocess.run(command, cwd=ROOT).returncode
        envelope_dir = args.output_dir / ENVELOPE_SUBDIR
        missing = missing_envelopes(envelope_dir, args.suite)
        if missing:
            print("[eval] 未生成 envelope，无法进入门禁：" + "、".join(missing), file=sys.stderr)
            return 1
        if not args.gate:
            return code
        if args.suite != "all":
            print("[eval] envelope 门禁要求四套件齐全；只跑单套件会判 NOT_RUN", file=sys.stderr)
        gate = [PYTHON, str(ROOT / "scripts/eval_prompt_gate.py"),
                "--candidate-dir", str(envelope_dir), "--mode", "envelope"]
        if args.fail_on_regression:
            gate.append("--fail-on-regression")
        return subprocess.run(gate, cwd=ROOT).returncode

    commands = build_commands(args)
    if args.dry_run:
        print(json.dumps([{"name": name, "command": command} for name, command in commands],
                         ensure_ascii=False, indent=2))
        return 0

    if args.preflight:
        ok, detail = preflight_model()
        print(f"[preflight] {'OK' if ok else 'FAIL'}：{detail}", flush=True)
        if not ok:
            print("[preflight] 模型服务不可用，已取消本轮评测", file=sys.stderr)
            return 1

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
        if args.retest_attempts:
            gate += ["--retest-attempts", str(args.retest_attempts)]
        return subprocess.run(gate, cwd=ROOT).returncode
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())