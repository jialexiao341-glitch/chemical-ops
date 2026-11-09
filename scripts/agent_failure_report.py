"""生成 Agent 失败与反馈周报；只读数据库，不调用模型。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai.failure_report import render_markdown, summarize  # noqa: E402
from app.modules.ai.model import AIAgentTask, AIFeedback  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="统计窗口天数")
    parser.add_argument("--limit", type=int, default=10, help="每个分组保留的条目数")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/agent-failure-report.json",
                        help="JSON 报告路径")
    parser.add_argument("--markdown", type=Path, default=None,
                        help="Markdown 报告路径；默认与 JSON 同名 .md")
    args = parser.parse_args()
    if args.days < 1 or args.limit < 1:
        parser.error("days 和 limit 必须为正数")

    since = datetime.now() - timedelta(days=args.days)
    with SessionLocal() as db:
        tasks = list(db.scalars(select(AIAgentTask).where(
            AIAgentTask.created_at >= since).order_by(AIAgentTask.created_at.desc())).all())
        feedbacks = list(db.scalars(select(AIFeedback).where(
            AIFeedback.created_at >= since)).all())

    report = summarize(tasks, feedbacks, days=args.days, limit=args.limit)
    output = args.output
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({
        "tasks": report["tasks"], "failed_tasks": report["failed_tasks"],
        "feedback": report["feedback"], "output": str(output), "markdown": str(markdown),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())