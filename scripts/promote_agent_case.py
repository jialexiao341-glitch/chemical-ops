"""把一条已审阅的差评任务导出为路由回归用例；不保存用户身份和任务原文。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai.capabilities import AGENT_TASK_REQUIREMENTS  # noqa: E402
from app.modules.ai.model import AIAgentTask  # noqa: E402


def build_case(task, *, question: str, expected_mode: str, expected_tasks: list[str],
               forbidden_tasks: list[str], note: str = "") -> dict:
    """构造脱敏用例；只保留问题、路由契约和 prompt 版本。"""
    meta = (task.payload or {}).get("run_meta") or {}
    called = {entry.get("tool") for entry in (task.payload or {}).get("trace") or []
              if entry.get("action") == "call_tool" and entry.get("tool")}
    derived = [task_name for task_name, required in AGENT_TASK_REQUIREMENTS.items()
               if required <= called]
    tasks = expected_tasks or derived
    if not tasks:
        raise ValueError("无法从任务轨迹推导预期任务，请显式提供 --expected-task")
    digest = hashlib.sha256((question + "|" + ",".join(sorted(tasks))).encode("utf-8")).hexdigest()[:8]
    return {
        "id": f"PR-{digest}",
        "question": question,
        "expected_execution_mode": expected_mode,
        "expected_tasks": sorted(set(tasks)),
        "forbidden_tasks": sorted(set(forbidden_tasks)),
        "source_task_hash": hashlib.sha256(str(task.id).encode("utf-8")).hexdigest()[:12],
        "source_prompt_version": (meta.get("prompt_versions") or {}).get("planner"),
        "created_at": datetime.now().date().isoformat(),
        "note": note,
    }


def append_case(path: Path, case: dict) -> list[dict]:
    """追加用例；同 id 或同来源任务哈希已存在时拒绝重复登记。"""
    cases = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(cases, list):
        raise ValueError(f"{path} 不是 JSON 数组")
    if any(item.get("id") == case["id"] for item in cases):
        raise ValueError(f"用例 {case['id']} 已存在")
    if any(item.get("source_task_hash") == case["source_task_hash"] for item in cases):
        raise ValueError("该任务已登记过回归用例")
    cases.append(case)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--question", help="人工脱敏后的问题；默认使用任务首轮输入")
    parser.add_argument("--allow-raw-question", action="store_true",
                        help="允许直接使用任务原文（仅限已确认不含敏感信息）")
    parser.add_argument("--expected-mode", choices=("agent", "batch", "query", "document", "none"),
                        default="agent")
    parser.add_argument("--expected-task", action="append", default=[],
                        help="预期任务类别，可重复；缺省时按轨迹工具推导")
    parser.add_argument("--forbidden-task", action="append", default=[],
                        help="禁止出现的任务类别，可重复")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/prod-regression/cases.json")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        task = db.scalar(select(AIAgentTask).where(AIAgentTask.id == args.task_id))
        if task is None:
            print("任务不存在", file=sys.stderr)
            return 1
        raw_question = ((task.payload or {}).get("messages") or [""])[0]
        question = args.question or raw_question
        if not args.question and not args.allow_raw_question:
            print("默认不直接使用任务原文；请用 --question 提供脱敏后的问题，"
                  "或确认无敏感信息后加 --allow-raw-question", file=sys.stderr)
            return 1
        try:
            case = build_case(task, question=question, expected_mode=args.expected_mode,
                              expected_tasks=args.expected_task,
                              forbidden_tasks=args.forbidden_task, note=args.note)
            cases = append_case(args.output, case)
        except ValueError as exc:
            print(f"登记失败：{exc}", file=sys.stderr)
            return 1

    print(json.dumps({"case": case, "total": len(cases), "output": str(args.output)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())