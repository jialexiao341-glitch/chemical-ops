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
from app.modules.ai_agent.capabilities import AGENT_TASK_REQUIREMENTS  # noqa: E402
from app.modules.ai_agent.model import AIAgentTask  # noqa: E402


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


def task_from_report_row(path: Path, row: dict, prompt_versions: dict | None = None) -> SimpleNamespace:
    """把报告中的一条用例适配成 build_case 需要的任务快照。"""
    question = str(row.get("question") or "")
    if not question:
        raise ValueError(f"用例 {row.get('id') or '?'} 没有问题文本")
    rounds = row.get("rounds") or []
    trace = (rounds[-1].get("trace") if rounds else []) or (row.get("actual") or {}).get("trace", [])
    return SimpleNamespace(
        id=f"{path.name}:{row.get('id') or question}",
        payload={"messages": [question], "trace": trace,
                 "run_meta": {"prompt_versions": prompt_versions or {}}},
    )


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
    versions = prompt_versions or report.get("prompt_versions") or {}
    return task_from_report_row(path, row, versions)


def case_failed(row: dict) -> bool:
    """用例任一轮未通过即视为失败候选；只认显式 passed 字段，避免把轨迹轮次误判为失败。"""
    if "passed" in row and not row["passed"]:
        return True
    for round_data in (row.get("rounds") or []):
        if isinstance(round_data, dict) and "passed" in round_data and not round_data["passed"]:
            return True
    return False


def derive_tasks_from_tools(tools: list[str] | None) -> list[str]:
    """按冻结的期望工具集推导任务类别；业务报告只有 required_tools，没有任务字段。"""
    provided = set(tools or [])
    return [name for name, required in AGENT_TASK_REQUIREMENTS.items()
            if required and required <= provided]


def select_report_rows(rows: list[dict], *, case_ids: list[str] | None = None,
                       failed_only: bool = False) -> list[dict]:
    """批量选择用例：显式编号优先，否则按失败筛选；两者都为空时拒绝全量导出。"""
    if case_ids:
        wanted = set(case_ids)
        selected = [row for row in rows
                    if str(row.get("id") or row.get("question")) in wanted]
    else:
        selected = [row for row in rows if case_failed(row)]
    if not selected:
        raise ValueError("没有匹配的用例可供登记")
    return selected


def resolve_mode(row: dict, requested: str) -> str:
    """auto 时按报告里的期望/实际执行模式取，缺省 agent。"""
    if requested != "auto":
        return requested
    return str(row.get("expected_execution_mode") or row.get("actual_mode") or "agent")


def resolve_tasks(row: dict, explicit: list[str]) -> list[str]:
    if explicit:
        return list(explicit)
    for field in ("expected_tasks", "actual_tasks"):
        if row.get(field):
            return list(row[field])
    return derive_tasks_from_tools(row.get("required_tools"))


def load_cases(path: Path) -> list[dict]:
    if not path.exists():
        return []
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError(f"{path} 不是 JSON 数组")
    return cases


def save_cases(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_case(path: Path, case: dict) -> list[dict]:
    """追加用例；同 id 或同来源任务哈希已存在时拒绝重复登记。"""
    cases = load_cases(path)
    if any(item.get("id") == case["id"] for item in cases):
        raise ValueError(f"用例 {case['id']} 已存在")
    if any(item.get("source_task_hash") == case["source_task_hash"] for item in cases):
        raise ValueError("该任务已登记过回归用例")
    cases.append(case)
    save_cases(path, cases)
    return cases


def append_cases(path: Path, new_cases: list[dict], *, persist: bool = True
                 ) -> tuple[list[dict], list[dict]]:
    """批量追加：重复用例跳过而不是中断整批，返回（已写入、跳过）。"""
    cases = load_cases(path)
    known_ids = {str(item.get("id")) for item in cases if item.get("id")}
    known_sources = {str(item.get("source_task_hash")) for item in cases
                     if item.get("source_task_hash")}
    written: list[dict] = []
    skipped: list[dict] = []
    for case in new_cases:
        if str(case["id"]) in known_ids:
            skipped.append({"id": case["id"], "reason": "该问题已登记"})
            continue
        if str(case.get("source_task_hash")) in known_sources:
            skipped.append({"id": case["id"], "reason": "该来源已登记"})
            continue
        cases.append(case)
        known_ids.add(str(case["id"]))
        if case.get("source_task_hash"):
            known_sources.add(str(case["source_task_hash"]))
        written.append({"id": case["id"], "question": case["question"]})
    if written and persist:
        save_cases(path, cases)
    return written, skipped


def build_cases_from_report(report_path: Path, rows: list[dict], args,
                            versions: dict | None = None) -> tuple[list[dict], list[dict]]:
    """批量构造用例；单条推导失败只记入 failed，不中断整批。"""
    versions = versions or {}
    cases: list[dict] = []
    failed: list[dict] = []
    for row in rows:
        case_id = str(row.get("id") or row.get("question"))
        try:
            task = task_from_report_row(report_path, row, versions)
            case = build_case(task, question=str(row.get("question") or ""),
                              expected_mode=resolve_mode(row, args.expected_mode),
                              expected_tasks=resolve_tasks(row, args.expected_task),
                              forbidden_tasks=args.forbidden_task, note=args.note)
        except ValueError as exc:
            failed.append({"id": case_id, "reason": str(exc)})
            continue
        cases.append(case)
    return cases, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", help="生产任务编号；与 --report 二选一")
    parser.add_argument("--report", type=Path, help="从已审阅的评测报告 JSON 登记用例")
    parser.add_argument("--case-id", help="报告中的用例编号，如 B007、T15")
    parser.add_argument("--case-ids", nargs="+", help="批量：报告中的多个用例编号")
    parser.add_argument("--failed-only", action="store_true", help="批量：报告内所有失败用例")
    parser.add_argument("--dry-run", action="store_true", help="批量：只预览，不写文件")
    parser.add_argument("--question", help="人工脱敏后的问题；默认使用任务首轮输入")
    parser.add_argument("--allow-raw-question", action="store_true",
                        help="允许直接使用任务原文（仅限已确认不含敏感信息）")
    parser.add_argument("--expected-mode",
                        choices=("agent", "batch", "query", "document", "none", "auto"),
                        default="agent",
                        help="auto 时取报告用例的期望/实际执行模式")
    parser.add_argument("--expected-task", action="append", default=[],
                        help="预期任务类别，可重复；缺省时按轨迹工具推导")
    parser.add_argument("--forbidden-task", action="append", default=[],
                        help="禁止出现的任务类别，可重复")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/prod-regression/cases.json")
    args = parser.parse_args(argv)

    batch = bool(args.case_ids or args.failed_only)
    if bool(args.report) == bool(args.task_id):
        parser.error("请二选一：--task-id 或 --report")
    if batch and args.task_id:
        parser.error("批量模式仅支持 --report")
    if args.case_id and batch:
        parser.error("--case-id 与 --case-ids/--failed-only 不能同时使用")
    if args.report and not (args.case_id or batch):
        parser.error("--report 需要 --case-id、--case-ids 或 --failed-only")
    if args.dry_run and not batch:
        parser.error("--dry-run 仅用于批量登记")
    if batch and args.question:
        parser.error("批量模式不支持 --question；问题取自报告用例")
    if batch and not args.allow_raw_question:
        print("批量登记默认不使用报告原文；确认用例问题不含敏感信息后加 --allow-raw-question",
              file=sys.stderr)
        return 1

    if args.report:
        try:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            rows = report.get("cases")
            if not isinstance(rows, list):
                raise ValueError(f"{args.report} 不是含 cases 列表的评测报告")
        except (OSError, ValueError) as exc:
            print(f"读取评测报告失败：{exc}", file=sys.stderr)
            return 1
        if batch:
            try:
                selected = select_report_rows(rows, case_ids=args.case_ids,
                                              failed_only=args.failed_only)
            except ValueError as exc:
                print(f"登记失败：{exc}", file=sys.stderr)
                return 1
            cases, failed = build_cases_from_report(args.report, selected, args,
                                                    report.get("prompt_versions") or {})
            if not cases:
                print(json.dumps({"written": [], "skipped": [], "failed": failed,
                                  "total": len(load_cases(args.output))}, ensure_ascii=False))
                return 1
            written, skipped = append_cases(args.output, cases, persist=not args.dry_run)
            print(json.dumps({"dry_run": args.dry_run, "written": written,
                              "skipped": skipped, "failed": failed,
                              "total": len(load_cases(args.output))}, ensure_ascii=False))
            if args.dry_run:
                return 0
            return 0 if written else 0
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