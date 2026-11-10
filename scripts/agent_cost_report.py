"""按场景、模型和 prompt 版本聚合 Agent 任务 token 与估算费用；只读数据库，不调用模型。

费用只用于运营观察，不参与业务判断。缺少 usage 的历史任务只统计 token 总量，
不伪造输入/输出拆分或费用；报告会单独列出覆盖率。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.ai.cost_report import (  # noqa: E402,F401
    build_report,
    collect_rows,
    percentile,
    summarize,
    summary,
)


def _fmt(value: object, digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _rate(value: object) -> str:
    return "—" if value is None else f"{float(value):.1%}"


def render_markdown(report: dict) -> str:
    """生成可直接贴入周报的 Markdown；费用列为估算值。"""
    pricing = report["pricing"]
    lines = [
        f"# Agent token 与费用报告（最近 {report['days']} 天）",
        "",
        "范围：只读任务运行元数据，按场景、模型和 prompt 版本聚合；不含用户身份和任务原文。",
        f"单价：输入 {pricing['input_per_million']} / 百万 token，输出 "
        f"{pricing['output_per_million']} / 百万 token"
        + ("" if pricing["configured"] else "（未配置，费用不估算）"),
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "| --- | ---: |",
    ]
    summary_data = report["summary"]
    lines += [
        f"| 任务数 | {summary_data['tasks']} |",
        f"| 成功 / 成功率 | {summary_data['succeeded']} / {_rate(summary_data['success_rate'])} |",
        f"| 输入 token | {_fmt(summary_data['input_tokens'])} |",
        f"| 输出 token | {_fmt(summary_data['output_tokens'])} |",
        f"| 总 token | {_fmt(summary_data['total_tokens'])} |",
        f"| 估算费用 | {_fmt(summary_data['estimated_cost'], 4)} |",
        f"| P50 / P95 墙钟耗时（秒） | {_fmt(summary_data['p50_seconds'], 2)} / "
        f"{_fmt(summary_data['p95_seconds'], 2)} |",
    ]
    for title, key, field in (("按场景", "by_scene", "scene"),
                              ("按模型", "by_model", "model"),
                              ("按 prompt 版本", "by_prompt_version", "prompt_version")):
        lines += ["", f"## {title}", "",
                  f"| {title[1:].strip()} | 任务 | 成功率 | 输入 token | 输出 token | 总 token | 估算费用 | P50 | P95 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        rows = report.get(key) or []
        if not rows:
            lines.append("| 无 | 0 | — | 0 | 0 | 0 | — | — | — |")
        for row in rows:
            lines.append(
                f"| {row[field]} | {row['tasks']} | {_rate(row['success_rate'])} | "
                f"{_fmt(row['input_tokens'])} | {_fmt(row['output_tokens'])} | "
                f"{_fmt(row['total_tokens'])} | {_fmt(row['estimated_cost'], 4)} | "
                f"{_fmt(row['p50_seconds'], 2)} | {_fmt(row['p95_seconds'], 2)} |")
    coverage = report["coverage"]
    lines += [
        "", "## 覆盖率", "",
        f"- 有 run_meta 用量：{coverage['run_meta_usage']} / {coverage['tasks']}",
        f"- 只有 token_budget 总量：{coverage['token_budget_only']}",
        f"- 无用量：{coverage['unmetered']}；无任务记录：{coverage['missing']}",
        f"- 模型调用 {coverage['calls']} 次，其中缺 usage {coverage['unmetered_calls']} 次、"
        f"缺输入/输出拆分 {coverage['split_unavailable_calls']} 次",
        "",
        "费用只按有输入/输出拆分的任务估算；`token_budget` 旧任务不伪造费用。",
        f"耗时只统计已终止任务（{coverage['tasks_with_duration']} / {coverage['terminal_tasks']}）；"
        "按 created_at→updated_at 的墙钟计算，包含排队和等待续答，不是单次模型调用延迟。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=30, help="统计窗口天数")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs/evaluation/agent-cost-report.json",
                        help="JSON 报告路径")
    parser.add_argument("--markdown", type=Path, default=None,
                        help="Markdown 路径；默认与 JSON 同名 .md")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("days 必须为正数")

    settings = get_settings()
    with SessionLocal() as db:
        report = summary(db, days=args.days,
                         price_in=settings.llm_price_input_per_million,
                         price_out=settings.llm_price_output_per_million,
                         default_model=settings.llm_model)
    output = args.output
    markdown = args.markdown or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({
        "tasks": report["summary"]["tasks"],
        "coverage": report["coverage"],
        "output": str(output),
        "markdown": str(markdown),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())