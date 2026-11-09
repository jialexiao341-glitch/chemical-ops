"""回放已审阅的生产差评路由用例；输出与评测门禁兼容的报告。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.modules.ai import routing  # noqa: E402
from app.modules.ai.capabilities import AGENT_TASK_REQUIREMENTS  # noqa: E402
from app.modules.ai.prompt_registry import prompt_version  # noqa: E402
from app.modules.ai.schema import CapabilityManifest  # noqa: E402
from app.modules.ai.agent_tools import TOOLS  # noqa: E402


def build_manifest() -> CapabilityManifest:
    """评测使用全量只读能力；真实账号权限仍由生产路由清单裁剪。"""
    tools = [{
        "name": spec.name, "description": spec.description,
        **spec.governance_metadata(),
        "input_schema": spec.input_schema.model_json_schema(),
    } for spec in TOOLS.values()]
    return CapabilityManifest(
        contract_version="1", digest="prod-regression-eval",
        agent_tools=tools, analytics_datasets=[], document_search=False,
        resource_scopes=[], action_proposals=[],
        agent_tasks=sorted(AGENT_TASK_REQUIREMENTS),
    )


def check_decision(decision, case: dict) -> dict:
    """只核对执行模式、必需任务和禁止任务；不把回答质量算作通过。"""
    mode_ok = decision.execution_mode == case["expected_execution_mode"]
    tasks = set(decision.tasks)
    expected_ok = set(case.get("expected_tasks") or []) <= tasks
    forbidden_ok = not (set(case.get("forbidden_tasks") or []) & tasks)
    return {
        "execution_mode": mode_ok,
        "expected_tasks": expected_ok,
        "forbidden_tasks": forbidden_ok,
        "passed": mode_ok and expected_ok and forbidden_ok,
        "actual_mode": decision.execution_mode,
        "actual_tasks": sorted(tasks),
    }


async def evaluate(cases: list[dict]) -> dict:
    manifest = build_manifest()
    results = []
    for case in cases:
        try:
            decision = await routing.understand(case["question"], {}, manifest=manifest)
        except Exception as exc:
            results.append({
                "id": case["id"], "question": case["question"], "passed": False,
                "checks": {"execution_mode": False, "expected_tasks": False,
                           "forbidden_tasks": False, "passed": False},
                "error_type": type(exc).__name__,
            })
            continue
        checks = check_decision(decision, case)
        results.append({
            "id": case["id"], "question": case["question"], "passed": checks["passed"],
            "checks": checks, "actual_mode": checks["actual_mode"],
            "actual_tasks": checks["actual_tasks"],
        })
    model_settings = get_settings()
    return {
        "dataset_version": "prod-regression-v1",
        "model": model_settings.llm_model,
        "prompt_versions": {
            "routing": prompt_version("routing"),
            "planner": prompt_version("planner"),
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases": results,
        "total": len(results),
        "passed": sum(1 for row in results if row["passed"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path,
                        default=ROOT / "docs/evaluation/prod-regression/cases.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/prod-regression/report.json")
    parser.add_argument("--only", nargs="+", help="只运行指定用例编号")
    parser.add_argument("--fail-on-failure", action="store_true")
    args = parser.parse_args(argv)

    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"读取用例失败：{exc}", file=sys.stderr)
        return 1
    if not isinstance(cases, list) or not cases:
        print("用例文件为空", file=sys.stderr)
        return 1
    if args.only:
        selected = set(args.only)
        cases = [case for case in cases if case.get("id") in selected]
        if not cases:
            print("没有匹配的用例", file=sys.stderr)
            return 1

    report = asyncio.run(evaluate(cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"total": report["total"], "passed": report["passed"],
                      "output": str(args.output)}, ensure_ascii=False))
    if args.fail_on_failure and report["passed"] != report["total"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())