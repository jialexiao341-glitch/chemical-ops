"""把一条已审阅的差评任务导出为路由回归用例；不保存用户身份和任务原文。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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
    if not tasks and expected_mode != "none":
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


def task_from_report(path: Path, case_id: str, prompt_versions: dict | None = None) -> SimpleNamespace:
    """把已审阅的评测报告用例适配成 build_case 需要的任务快照。

    评测轨迹不是生产数据库任务；这里只用报告中的问题、最终轨迹和 prompt 版本，
    不保存用户身份，也不把评测输入写回任务库。
    """
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("cases")
    if not isinstance(rows, list):
        raise ValueError(f"{path} 不是含 cases 列表的评测报告")
    row = next((item for item in rows
                if str(item.get("id") or item.get("question")) == case_id), None)
    if row is None:
        raise ValueError(f"报告中不存在用例 {case_id}")
    question = str(row.get("question") or "")
    if not question:
        raise ValueError(f"用例 {case_id} 没有问题文本")
    rounds = row.get("rounds") or []
    trace = (rounds[-1].get("trace") if rounds else []) or (row.get("actual") or {}).get("trace", [])
    versions = prompt_versions or report.get("prompt_versions") or {}
    return SimpleNamespace(
        id=f"{path.name}:{case_id}",
        payload={"messages": [question], "trace": trace, "run_meta": {"prompt_versions": versions}},
    )


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
    parser.add_argument("--task-id", help="生产任务编号；与 --report 二选一")
    parser.add_argument("--report", type=Path, help="从已审阅的评测报告 JSON 登记用例")
    parser.add_argument("--case-id", help="报告中的用例编号，如 B007、T15")
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

    if bool(args.report) == bool(args.task_id):
        parser.error("请二选一：--task-id 或 --report")
    if args.report and not args.case_id:
        parser.error("--report 需要同时提供 --case-id")

    if args.report:
        try:
            task = task_from_report(args.report, args.case_id)
        except (OSError, ValueError) as exc:
            print(f"读取评测报告失败：{exc}", file=sys.stderr)
            return 1
    else:
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