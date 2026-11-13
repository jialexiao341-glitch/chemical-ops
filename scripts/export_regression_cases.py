"""把已批准的回归用例导出为评测用例文件；合并现有手工用例，不导出任务原文或用户身份。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai_agent.model import AIRegressionCase  # noqa: E402


def case_payload(row: AIRegressionCase) -> dict:
    """只导出评测需要的公开契约；不导出 source_task_id、创建人或审阅人。"""
    return {
        "id": row.case_key,
        "question": row.question,
        "expected_execution_mode": row.expected_execution_mode,
        "expected_tasks": row.expected_tasks or [],
        "forbidden_tasks": row.forbidden_tasks or [],
        "source_task_hash": row.source_task_hash,
        "source_prompt_version": row.source_prompt_version,
        "created_at": row.created_at.date().isoformat() if row.created_at else None,
        "note": row.note or "",
    }


def merge_cases(existing: list[dict], approved: list[dict]) -> list[dict]:
    """保留现有用例顺序；同编号以数据库已批准版本覆盖，新用例追加。"""
    by_id = {
        str(row.get("id")): row for row in existing
        if isinstance(row, dict) and row.get("id")
    }
    ordered = [row for row in existing if isinstance(row, dict) and row.get("id")]
    existing_ids = set(by_id)
    for row in approved:
        key = str(row.get("id"))
        if key in by_id:
            by_id[key] = row
        else:
            by_id[key] = row
            ordered.append(row)
    result = []
    for row in ordered:
        key = str(row.get("id"))
        result.append(by_id.get(key, row))
    if not existing_ids:
        result = list(approved)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/prod-regression/cases.json",
                        help="评测用例 JSON 路径")
    parser.add_argument("--replace", action="store_true",
                        help="不合并现有手工用例，只写入已批准用例")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        rows = list(db.scalars(
            select(AIRegressionCase)
            .where(AIRegressionCase.status == "APPROVED")
            .order_by(AIRegressionCase.created_at, AIRegressionCase.id)
        ).all())
    approved = [case_payload(row) for row in rows]

    existing: list[dict] = []
    if args.output.exists() and not args.replace:
        loaded = json.loads(args.output.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            print("现有用例文件不是 JSON 数组", file=sys.stderr)
            return 1
        existing = loaded
    merged = approved if args.replace else merge_cases(existing, approved)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "approved": len(approved), "existing": len(existing),
        "total": len(merged), "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
