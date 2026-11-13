"""用合成差评样本测量“候选→脱敏入库→批准→导出”的机器耗时。

样本与审批记录均为 fixture，**不是生产数据**：脚本只测量应用侧流水线耗时，
不测量人工审阅时间，也不能据此宣称“转化 ≤1 天”。生产转化时长必须用真实任务、
真实差评和真实管理员操作记录统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.modules.ai_agent.quality_operations import regression_cases  # noqa: E402
from app.modules.ai_agent.model import AIAgentTask, AIFeedback  # noqa: E402
from app.modules.ai_agent.schema import RegressionCaseBatchCreate, RegressionCaseBatchReview  # noqa: E402
from app.modules.system_management.model import User  # noqa: E402
from scripts.export_regression_cases import case_payload  # noqa: E402

DEFAULT_FIXTURES = ROOT / "docs/evaluation/regression-conversion-fixtures/feedback-samples.json"
DEFAULT_APPROVALS = ROOT / "docs/evaluation/regression-conversion-fixtures/approval-records.json"

_DDL = (
    """CREATE TABLE ai_agent_tasks (
        id VARCHAR(32) PRIMARY KEY, user_id INTEGER NOT NULL, status VARCHAR(24) NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0, payload JSON NOT NULL, reply TEXT NOT NULL,
        error_code VARCHAR(64), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE ai_feedback (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, task_id VARCHAR(32) NOT NULL,
        rating VARCHAR(8) NOT NULL, reason_code VARCHAR(32), comment VARCHAR(1000),
        correction TEXT, prompt_version VARCHAR(100), prompt_versions JSON,
        model_name VARCHAR(100), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE ai_regression_cases (
        id INTEGER PRIMARY KEY, case_key VARCHAR(64) NOT NULL UNIQUE,
        source_task_id VARCHAR(32), source_task_hash VARCHAR(64),
        source_prompt_version VARCHAR(100), question TEXT NOT NULL,
        expected_execution_mode VARCHAR(16) NOT NULL, expected_tasks JSON NOT NULL,
        forbidden_tasks JSON NOT NULL, note VARCHAR(500),
        status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', created_by INTEGER NOT NULL,
        reviewed_by INTEGER, reviewed_at DATETIME, created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )""",
)


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 不是 JSON 对象")
    if data.get("kind") is None:
        raise ValueError(f"{path} 缺少 kind")
    return data


def build_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in _DDL:
            connection.execute(text(statement))
    return Session(engine, autoflush=False, expire_on_commit=False)


def seed(db: Session, fixtures: dict) -> None:
    now = datetime.now()
    for sample in fixtures["samples"]:
        created = now - timedelta(minutes=int(sample.get("minutes_ago", 0)))
        trace = [{"action": "call_tool", "tool": tool}
                 for tool in sample.get("trace_tools") or []]
        db.add(AIAgentTask(
            id=sample["task_id"], user_id=int(fixtures["owner_user_id"]),
            status=sample.get("status", "SUCCEEDED"), revision=0,
            payload={"messages": [sample["question"]],
                     "run_meta": {"prompt_versions": {"routing": "routing@fixture",
                                                      "planner": "planner@fixture"}},
                     "trace": trace},
            reply="", error_code=sample.get("error_code"),
            created_at=created, updated_at=created,
        ))
        db.add(AIFeedback(
            id=None, user_id=int(fixtures["owner_user_id"]), task_id=sample["task_id"],
            rating=sample.get("rating", "DOWN"), reason_code=sample.get("reason_code"),
            comment=None, correction=None, prompt_version=None, prompt_versions=None,
            model_name=None, created_at=created, updated_at=created,
        ))
    db.commit()


def _timed(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _display_path(path: Path) -> str:
    """报告里用仓库相对路径，避免本机绝对路径泄露到证据文件。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def measure(fixtures_path: Path, approvals_path: Path) -> dict:
    fixtures = load_json(fixtures_path)
    approvals = load_json(approvals_path)
    samples = fixtures["samples"]
    decisions = {row["source_task_id"]: row for row in approvals["records"]}
    if len(samples) > 50:
        raise ValueError("fixture 样本超过批量接口上限 50 条")
    sample_ids = [sample["task_id"] for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("fixture 中 task_id 重复")
    missing = [task_id for task_id in sample_ids if task_id not in decisions]
    if missing:
        raise ValueError(f"缺少审批记录：{'、'.join(missing)}")
    unknown = [task_id for task_id in decisions if task_id not in set(sample_ids)]
    if unknown:
        raise ValueError(f"审批记录引用了不存在的样本：{'、'.join(unknown)}")
    invalid = [row for row in decisions.values()
               if row.get("decision") not in ("APPROVE", "ARCHIVE")]
    if invalid:
        raise ValueError("审批动作只能是 APPROVE 或 ARCHIVE")

    # benchmark 用固定管理员身份；真实环境仍由服务端按登录用户校验角色。
    regression_cases.get_user_role_codes = lambda *_args, **_kwargs: ["SYS_ADMIN"]
    user = User(id=int(fixtures["owner_user_id"]), username="synthetic-admin",
                status="ACTIVE", password_hash="fixture")

    db = build_db()
    seed_start = perf_counter()
    seed(db, fixtures)
    seed_ms = _timed(seed_start)

    candidates_start = perf_counter()
    page = regression_cases.candidate_drafts(
        db, user, days=int(fixtures.get("window_days", 7)), limit=50)
    candidates_ms = _timed(candidates_start)
    items = [item for item in page.items if item.source_task_id in decisions]
    if not items:
        raise ValueError("候选为空：检查 fixture 时间窗口与差评记录")

    create_start = perf_counter()
    created = regression_cases.create_cases_batch(
        db, user, RegressionCaseBatchCreate(
            items=[RegressionCaseBatchItemFixture.build(item) for item in items],
            redacted_confirmed=True))
    create_ms = _timed(create_start)

    approve_items = [item for item in items
                     if decisions[item.source_task_id].get("decision") == "APPROVE"]
    archive_items = [item for item in items
                     if decisions[item.source_task_id].get("decision") == "ARCHIVE"]
    id_by_source = {row.source_task_id: row.case_id for row in created.items
                    if row.case_id is not None}

    approve_start = perf_counter()
    approved = regression_cases.review_cases_batch(
        db, user, RegressionCaseBatchReview(
            case_ids=[id_by_source[item.source_task_id] for item in approve_items],
            action="APPROVE")) if approve_items else None
    approve_ms = _timed(approve_start)

    archive_start = perf_counter()
    archived = regression_cases.review_cases_batch(
        db, user, RegressionCaseBatchReview(
            case_ids=[id_by_source[item.source_task_id] for item in archive_items],
            action="ARCHIVE")) if archive_items else None
    archive_ms = _timed(archive_start)

    export_start = perf_counter()
    rows = regression_cases.list_cases(db, user, status="APPROVED", page_size=100).items
    payloads = [case_payload(db.get(regression_cases.AIRegressionCase, row.id)) for row in rows]
    export_ms = _timed(export_start)

    findings: dict[str, int] = {}
    for item in items:
        for key, count in (item.redaction_findings or {}).items():
            findings[key] = findings.get(key, 0) + int(count)

    elapsed_offsets = sorted(int(row.get("reviewed_offset_minutes", 0))
                             for row in decisions.values())
    return {
        "kind": "synthetic_conversion_benchmark",
        "production_measured": False,
        "fixtures": {"samples": _display_path(fixtures_path),
                     "approvals": _display_path(approvals_path)},
        "dataset": {
            "owner_user_id": int(fixtures["owner_user_id"]),
            "window_days": int(fixtures.get("window_days", 7)),
            "samples": len(samples),
        },
        "counts": {
            "candidates": len(items),
            "created": created.created,
            "reused": created.reused,
            "skipped_create": created.skipped,
            "failed_create": created.failed,
            "approved": approved.updated if approved else 0,
            "archived": archived.updated if archived else 0,
            "exported": len(payloads),
        },
        "stage_ms": {
            "seed": seed_ms,
            "candidates": candidates_ms,
            "batch_create": create_ms,
            "batch_approve": approve_ms,
            "batch_archive": archive_ms,
            "export": export_ms,
            "pipeline_excluding_seed": round(
                candidates_ms + create_ms + approve_ms + archive_ms + export_ms, 2),
        },
        "redaction_hits": findings,
        "approval_fixture": {
            "measured_human_time": False,
            "reviewed_offset_minutes_range": [elapsed_offsets[0], elapsed_offsets[-1]
                                               ] if elapsed_offsets else [],
            "note": "fixture 中的复核时间偏移只用于展示审批记录字段，不能当作人工耗时或转化时长",
        },
        "limitations": [
            "SQLite 内存库与本地进程内调用，不代表生产数据库、网络和并发开销",
            "审批由脚本以管理员身份代执行，不是真实人工审批记录",
            "合成问题不含真实客户信息；不能据此宣称生产转化 ≤1 天",
        ],
    }


class RegressionCaseBatchItemFixture:
    """把候选草稿转成批量提交项；避免脚本重复写字段映射。"""

    @staticmethod
    def build(item) -> dict:
        return {
            "source_task_id": item.source_task_id,
            "question": item.redacted_question,
            "expected_execution_mode": item.expected_execution_mode,
            "expected_tasks": item.expected_tasks,
            "forbidden_tasks": item.forbidden_tasks,
            "note": "synthetic-fixture",
        }


def render_markdown(result: dict) -> str:
    counts = result["counts"]
    stages = result["stage_ms"]
    hits = result["redaction_hits"]
    lines = [
        "# 回归用例转化流水线基准（合成样本）",
        "",
        "> 数据来源是仓库内合成 fixture，**不是生产差评，也不是真实人工审批记录**。",
        "> 本报告只测应用侧机器耗时，不能用于宣称“转化 ≤1 天”。",
        "",
        "## 样本与范围",
        "",
        f"- 合成差评样本：{result['dataset']['samples']} 条；时间窗口 {result['dataset']['window_days']} 天",
        f"- fixture：`{result['fixtures']['samples']}`、`{result['fixtures']['approvals']}`",
        "- 运行环境：SQLite 内存库，进程内调用真实服务函数",
        "",
        "## 数量结果",
        "",
        "| 候选 | 新建 | 复用 | 跳过 | 失败 | 批准 | 归档 | 导出 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {counts['candidates']} | {counts['created']} | {counts['reused']} | "
        f"{counts['skipped_create']} | {counts['failed_create']} | {counts['approved']} | "
        f"{counts['archived']} | {counts['exported']} |",
        "",
        "## 机器耗时（毫秒）",
        "",
        "| 阶段 | 毫秒 |",
        "| --- | ---: |",
        f"| 候选生成 | {stages['candidates']} |",
        f"| 批量脱敏入库 | {stages['batch_create']} |",
        f"| 批量批准 | {stages['batch_approve']} |",
        f"| 批量归档 | {stages['batch_archive']} |",
        f"| 导出 | {stages['export']} |",
        f"| 流水线合计（不含 fixture 建库） | {stages['pipeline_excluding_seed']} |",
        "",
        "## 脱敏命中（合成样本）",
        "",
        f"- {json.dumps(hits, ensure_ascii=False)}",
        "",
        "## 边界",
        "",
    ]
    lines += [f"- {item}" for item in result["limitations"]]
    lines += [
        "",
        "## 生产口径如何补",
        "",
        "1. 用真实任务的 `created_at`（首次反馈）与管理员 `reviewed_at` 计算人工转化时长。",
        "2. 只统计 `ai_regression_cases.status = 'APPROVED'` 且 `reviewed_at` 非空的记录。",
        "3. 按批次记录候选生成时间、批准时间和导出时间，避免用 fixture 时间偏移代替。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--approvals", type=Path, default=DEFAULT_APPROVALS)
    parser.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    parser.add_argument("--out", type=Path, help="同时写入 JSON 或 Markdown 报告")
    args = parser.parse_args(argv)
    try:
        result = measure(args.fixtures, args.approvals)
    except (OSError, ValueError) as exc:
        print(f"基准运行失败：{exc}", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        content = (json.dumps(result, ensure_ascii=False, indent=2) + "\n"
                   if args.out.suffix == ".json" else render_markdown(result) + "\n")
        args.out.write_text(content, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)
          if args.json else render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())