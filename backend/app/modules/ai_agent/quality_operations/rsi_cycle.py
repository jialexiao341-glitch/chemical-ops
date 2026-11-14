"""RSI 自动候选归集与只读实验报告装配。

职责边界：
1. 自动从近期差评（rating='DOWN'）与非基础设施失败任务中提取已脱敏的回归用例草稿（status='DRAFT'），
   复用 regression_cases 的权限校验、确定性脱敏与去重规则；绝不自动 APPROVE，绝不直接写入基线用例集。
2. 基于失败阶段、反馈原因码与脱敏后的用户纠正建议，汇总结构化改进建议（routing_prompt / tool_contract / planner_prompt），
   所有建议仅作人工审阅依据（auto_applied=False），绝不自动修改系统提示词或工具定义。
3. 可挂载只读对照实验（prompt_experiment）与门禁裁决（eval_prompt_gate）摘要，供人工决策是否批准或升级基线。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError
from app.modules.ai_agent.model import AIFeedback
from app.modules.ai_agent.quality_operations import quality_report, regression_cases
from app.modules.ai_agent.schema import (
    RegressionCaseBatchCreate,
    RegressionCaseBatchItem,
    RegressionCaseCandidate,
    RegressionCaseCandidatePage,
)
from app.modules.ai_agent.shared_utils.redaction import redact
from app.modules.system_management.model import User


@dataclass(frozen=True)
class _ProposalSpec:
    target_area: str
    target_symbol: str
    title: str
    stages: frozenset[str]
    reason_codes: frozenset[str]
    suggested_checks: tuple[str, ...]
    next_action: str


_PROPOSAL_SPECS: tuple[_ProposalSpec, ...] = (
    _ProposalSpec(
        target_area="routing_prompt",
        target_symbol="ROUTING_PROMPT",
        title="路由消歧与意图边界改进候选",
        stages=frozenset({"ROUTING"}),
        reason_codes=frozenset({"SCOPE_ERROR"}),
        suggested_checks=(
            "python scripts/evaluate_intent_routing.py",
            "python scripts/evaluate_page_context_routing.py",
            "python scripts/prompt_experiment.py --baseline-dir <baseline> --candidate-dir <candidate>",
        ),
        next_action="审阅关联草稿用例与用户纠正后，人工微调 ROUTING_PROMPT / page_context 槽位规则，再跑四套件对照实验。",
    ),
    _ProposalSpec(
        target_area="tool_contract",
        target_symbol="AGENT_TOOL_CONTRACTS",
        title="工具契约、参数校验与权限范围改进候选",
        stages=frozenset({"TOOL", "CONTEXT", "BUDGET"}),
        reason_codes=frozenset({"TOOL_ERROR"}),
        suggested_checks=(
            "python scripts/evaluate_agent_tasks.py",
            "python scripts/evaluate_agent_business.py --workers 3",
            "python scripts/prompt_experiment.py --baseline-dir <baseline> --candidate-dir <candidate>",
        ),
        next_action="核对涉及工具的输入 Schema、工具描述与无权限兜底提示，补充单测后跑任务与业务套件。",
    ),
    _ProposalSpec(
        target_area="planner_prompt",
        target_symbol="PLANNER_PROMPT",
        title="回答组织、依据引用与完整性改进候选",
        stages=frozenset({"PLANNER", "CONFIRM"}),
        reason_codes=frozenset({"FACT_ERROR", "FORMAT", "OTHER", "UNSPECIFIED"}),
        suggested_checks=(
            "python scripts/evaluate_agent_business.py --workers 3",
            "python scripts/eval_harness.py --suite all --repeat 3 --out-dir docs/evaluation/candidate/envelopes",
            "python scripts/prompt_experiment.py --baseline-dir <baseline> --candidate-dir <candidate>",
        ),
        next_action="检查状态成功但收到差评（down_on_success）及回答缺失项样本，人工优化 PLANNER_PROMPT 输出契约后复测。",
    ),
)

_MIN_QUESTION_CHARS = 5


def _draft_note(candidate: RegressionCaseCandidate) -> str:
    """生成带来源归因的脱敏草稿备注；限制长度并避免写入原始任务文本。"""
    note = (
        f"[auto-rsi] source={candidate.source} "
        f"stage={candidate.failure_stage or 'NONE'} "
        f"reason={candidate.feedback_reason_code or 'NONE'}"
    )
    if candidate.error_code:
        note += f" error={candidate.error_code}"
    return note[:500]


def _sync_with_page(
    db: Session,
    actor: User,
    candidate_page: RegressionCaseCandidatePage,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """把未入库且脱敏长度达标的候选转为 DRAFT 回归用例；支持只预览不落库。"""
    already_tracked = 0
    too_short = 0
    eligible: list[RegressionCaseCandidate] = []
    batch_items: list[RegressionCaseBatchItem] = []

    for candidate in candidate_page.items:
        if candidate.existing_case_id is not None:
            already_tracked += 1
            continue
        cleaned_question = candidate.redacted_question.strip()
        if len(cleaned_question) < _MIN_QUESTION_CHARS:
            too_short += 1
            continue
        eligible.append(candidate)
        batch_items.append(
            RegressionCaseBatchItem(
                source_task_id=candidate.source_task_id,
                question=cleaned_question,
                expected_execution_mode=candidate.expected_execution_mode,
                expected_tasks=list(candidate.expected_tasks),
                forbidden_tasks=list(candidate.forbidden_tasks),
                note=_draft_note(candidate),
            )
        )

    preview_items = [
        {
            "case_key": item.case_key,
            "source": item.source,
            "failure_stage": item.failure_stage,
            "feedback_reason_code": item.feedback_reason_code,
            "error_code": item.error_code,
            "redacted_question": item.redacted_question,
            "redaction_findings": item.redaction_findings,
        }
        for item in eligible
    ]

    if dry_run or not batch_items:
        return {
            "status": "DRY_RUN" if dry_run else "NO_NEW_CANDIDATES",
            "scanned": candidate_page.total,
            "eligible": len(eligible),
            "already_tracked": already_tracked,
            "too_short": too_short,
            "created": 0,
            "reused": 0,
            "skipped": 0,
            "failed": 0,
            "created_case_keys": [],
            "created_case_ids": [],
            "preview_items": preview_items,
        }

    batch_result = regression_cases.create_cases_batch(
        db,
        actor,
        RegressionCaseBatchCreate(redacted_confirmed=True, items=batch_items),
    )
    created_keys = [row.case_key for row in batch_result.items if row.status == "CREATED" and row.case_key]
    created_ids = [row.case_id for row in batch_result.items if row.status == "CREATED" and row.case_id is not None]
    return {
        "status": "SYNCED",
        "scanned": candidate_page.total,
        "eligible": len(eligible),
        "already_tracked": already_tracked,
        "too_short": too_short,
        "created": batch_result.created,
        "reused": batch_result.reused,
        "skipped": batch_result.skipped,
        "failed": batch_result.failed,
        "created_case_keys": created_keys,
        "created_case_ids": created_ids,
        "preview_items": preview_items,
    }


def sync_candidate_drafts(
    db: Session,
    actor: User,
    *,
    days: int = 7,
    limit: int = 20,
    include_infra: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """无需人工点选，自动把近期差评与有效失败任务归集为脱敏 DRAFT 回归用例。

    权限与边界：仅管理员可触发；默认排除基础设施抖动；始终只生成 DRAFT 草稿，
    绝不绕过人工审阅写入 APPROVED 或基线题集。
    """
    if not regression_cases._is_admin(db, actor):
        raise AuthorizationError("仅管理员可执行回归候选自动归集")
    candidate_page = regression_cases.candidate_drafts(
        db,
        actor,
        days=days,
        limit=limit,
        include_infra=include_infra,
    )
    return _sync_with_page(db, actor, candidate_page, dry_run=dry_run)


def _recent_redacted_corrections(db: Session, *, days: int, limit: int = 200) -> dict[str, str]:
    """读取窗口内差评任务对应的脱敏纠正文本；不返回用户身份。"""
    since = datetime.now() - timedelta(days=days)
    rows = db.scalars(
        select(AIFeedback)
        .where(AIFeedback.rating == "DOWN", AIFeedback.created_at >= since)
        .order_by(AIFeedback.created_at.desc())
        .limit(limit)
    ).all()
    corrections: dict[str, str] = {}
    for row in rows:
        raw = str(row.correction or row.comment or "").strip()
        if not raw or row.task_id in corrections:
            continue
        redacted = redact(raw).text.strip()
        if redacted:
            corrections[row.task_id] = redacted[:240]
    return corrections


def _match_spec(candidate: RegressionCaseCandidate) -> _ProposalSpec:
    """按失败阶段和差评原因将样本映射到对应的改进候选分类。"""
    stage = (candidate.failure_stage or "").upper()
    reason = (candidate.feedback_reason_code or "").upper()
    for spec in _PROPOSAL_SPECS:
        if stage in spec.stages or reason in spec.reason_codes:
            return spec
    return _PROPOSAL_SPECS[-1]


def _proposal_id(target_area: str, case_keys: list[str], error_codes: list[str]) -> str:
    seed = f"{target_area}|{','.join(sorted(case_keys))}|{','.join(sorted(error_codes))}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8].upper()
    return f"RSI-PROP-{digest}"


def build_improvement_proposals(
    db: Session,
    summary: dict[str, Any],
    candidate_page: RegressionCaseCandidatePage,
    *,
    days: int,
    max_proposals: int = 10,
) -> list[dict[str, Any]]:
    """从失败统计、差评纠正与候选草稿中聚合成只读改进提案，不改动任何提示词或代码。"""
    corrections_by_task = _recent_redacted_corrections(db, days=days)
    grouped: dict[str, list[RegressionCaseCandidate]] = {spec.target_area: [] for spec in _PROPOSAL_SPECS}
    for candidate in candidate_page.items:
        spec = _match_spec(candidate)
        grouped[spec.target_area].append(candidate)

    down_on_success = int((summary.get("case_conflict") or {}).get("down_on_success") or 0)
    top_tools = [str(row["key"]) for row in (summary.get("by_tool") or [])[:5] if row.get("key")]
    top_errors = [str(row["key"]) for row in (summary.get("by_error_code") or [])[:5] if row.get("key")]
    top_versions = [str(row["key"]) for row in (summary.get("by_prompt_version") or [])[:5] if row.get("key")]

    proposals: list[dict[str, Any]] = []
    for spec in _PROPOSAL_SPECS:
        items = grouped[spec.target_area]
        extra_signal = spec.target_area == "planner_prompt" and down_on_success > 0
        if not items and not extra_signal:
            continue

        case_keys = [item.case_key for item in items[:5]]
        error_codes = sorted({item.error_code for item in items if item.error_code}) or (
            top_errors[:3] if spec.target_area == "tool_contract" else []
        )
        reasons = sorted({item.feedback_reason_code for item in items if item.feedback_reason_code})
        corrections = []
        for item in items:
            text = corrections_by_task.get(item.source_task_id)
            if text and text not in corrections:
                corrections.append(text)
            if len(corrections) >= 3:
                break

        evidence_count = max(len(items), down_on_success if extra_signal else 0)
        proposals.append({
            "proposal_id": _proposal_id(spec.target_area, case_keys, error_codes),
            "target_area": spec.target_area,
            "target_symbol": spec.target_symbol,
            "title": spec.title,
            "evidence_count": evidence_count,
            "trigger_signals": {
                "stages": sorted({item.failure_stage for item in items if item.failure_stage}),
                "feedback_reasons": reasons,
                "error_codes": error_codes,
                "down_on_success": down_on_success if spec.target_area == "planner_prompt" else 0,
                "affected_tools": top_tools if spec.target_area == "tool_contract" else [],
                "prompt_versions": top_versions,
            },
            "sample_case_keys": case_keys,
            "redacted_corrections": corrections,
            "suggested_checks": list(spec.suggested_checks),
            "next_action": spec.next_action,
            "auto_applied": False,
            "requires_human_approval": True,
        })

    proposals.sort(key=lambda item: (-int(item["evidence_count"]), item["target_area"]))
    return proposals[:max_proposals]


def _compact_experiment(experiment: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    """裁剪 prompt_experiment 结果为 RSI 报告摘要，保留统计裁决与显著差异用例数。"""
    if error:
        return {"status": "FAILED", "verdict": "FAILED", "error": error, "suites": []}
    if not experiment:
        return {"status": "NOT_RUN", "verdict": "NOT_RUN", "suites": []}
    return {
        "status": "COMPLETED",
        "verdict": experiment.get("verdict"),
        "baseline_dir": experiment.get("baseline_dir"),
        "candidate_dir": experiment.get("candidate_dir"),
        "suites": [
            {
                "suite": row.get("suite"),
                "cases": row.get("cases"),
                "both_pass": row.get("both_pass"),
                "baseline_only": row.get("baseline_only"),
                "candidate_only": row.get("candidate_only"),
                "both_fail": row.get("both_fail"),
                "delta": row.get("delta"),
                "mcnemar_p": row.get("mcnemar_p"),
                "verdict": row.get("verdict"),
                "improved_keys": [item.get("key") for item in (row.get("improved") or [])],
                "degraded_keys": [item.get("key") for item in (row.get("degraded") or [])],
            }
            for row in (experiment.get("suites") or [])
        ],
    }


def _compact_gate(gate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gate:
        return None
    return {
        "verdict": gate.get("verdict"),
        "prompt_key": gate.get("prompt_key"),
        "missing": gate.get("missing") or [],
        "warnings": gate.get("warnings") or [],
        "reports": [
            {
                "name": row.get("name"),
                "baseline_passed": row.get("baseline_passed"),
                "baseline_total": row.get("baseline_total"),
                "candidate_passed": row.get("candidate_passed"),
                "candidate_total": row.get("candidate_total"),
                "verdict": row.get("verdict"),
                "regressions": len(row.get("regressions") or []),
                "unstable": len(row.get("unstable") or []),
                "safety_failures": len(row.get("safety_failures") or []),
            }
            for row in (gate.get("reports") or [])
        ],
    }


def build_rsi_cycle_report(
    db: Session,
    actor: User,
    *,
    days: int = 7,
    limit: int = 20,
    include_infra: bool = False,
    dry_run: bool = False,
    experiment_summary: dict[str, Any] | None = None,
    gate_summary: dict[str, Any] | None = None,
    experiment_error: str | None = None,
) -> dict[str, Any]:
    """执行完整一轮只读/草稿级 RSI 自改进巡检，产出结构化闭环报告。"""
    if not regression_cases._is_admin(db, actor):
        raise AuthorizationError("仅管理员可执行 RSI 巡检周期")
    candidate_page = regression_cases.candidate_drafts(
        db,
        actor,
        days=days,
        limit=limit,
        include_infra=include_infra,
    )
    sync = _sync_with_page(db, actor, candidate_page, dry_run=dry_run)
    summary = quality_report.summarize(db, days=days, limit=10)
    proposals = build_improvement_proposals(db, summary, candidate_page, days=days)
    return {
        "kind": "rsi_cycle_report",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "guardrails": {
            "candidate_generation": "DRAFT_ONLY",
            "baseline_auto_promotion": False,
            "prompt_auto_mutation": False,
        },
        "quality_snapshot": {
            "tasks": summary.get("tasks", 0),
            "failed_tasks": summary.get("failed_tasks", 0),
            "feedback": summary.get("feedback", 0),
            "up": summary.get("up", 0),
            "down": summary.get("down", 0),
            "down_rate": summary.get("down_rate"),
            "down_on_success": (summary.get("case_conflict") or {}).get("down_on_success", 0),
        },
        "candidate_sync": sync,
        "improvement_proposals": proposals,
        "experiment": _compact_experiment(experiment_summary, experiment_error),
        "gate": _compact_gate(gate_summary),
    }


def render_rsi_markdown(report: dict[str, Any]) -> str:
    """生成面向管理员审阅的 RSI 巡检与实验结论 Markdown；不含未脱敏原文。"""
    snap = report.get("quality_snapshot") or {}
    sync = report.get("candidate_sync") or {}
    proposals = report.get("improvement_proposals") or []
    experiment = report.get("experiment") or {}
    gate = report.get("gate")

    down_rate = snap.get("down_rate")
    down_rate_text = f"（差评率 {down_rate:.1%}）" if isinstance(down_rate, (int, float)) else ""
    lines = [
        f"# Agent RSI 自改进巡检与实验报告（最近 {report.get('days', 7)} 天）",
        "",
        f"- 生成时间：{report.get('generated_at', '-')}",
        "- 安全红线：仅自动生成 `DRAFT` 脱敏回归用例与只读改进提案；禁止自动改写提示词与自动晋升基线",
        f"- 观测样本：任务 {snap.get('tasks', 0)} 个，失败 {snap.get('failed_tasks', 0)} 个，"
        f"反馈 {snap.get('feedback', 0)} 条（差评 {snap.get('down', 0)}{down_rate_text}，状态成功但差评 {snap.get('down_on_success', 0)} 个）",
        "",
        "## 1. 候选回归用例自动归集（DRAFT）",
        "",
        "| 指标 | 数量 |",
        "| --- | ---: |",
        f"| 执行模式 | {sync.get('status', '-')} |",
        f"| 扫描候选 | {sync.get('scanned', 0)} |",
        f"| 符合条件待入库 | {sync.get('eligible', 0)} |",
        f"| 新建草稿 (`CREATED`) | {sync.get('created', 0)} |",
        f"| 已有跟踪/跳过 (`already_tracked` + `reused` + `skipped`) | {int(sync.get('already_tracked', 0)) + int(sync.get('reused', 0)) + int(sync.get('skipped', 0))} |",
        "",
    ]
    created_keys = sync.get("created_case_keys") or []
    if created_keys:
        lines += [f"- 新建草稿编号：{', '.join(created_keys)}", ""]

    lines += ["## 2. 失败聚类与只读改进提案", ""]
    if not proposals:
        lines += ["- 当前统计窗口未命中需重点排查的路由/工具/回答质量聚集项。", ""]
    else:
        lines += ["| 提案编号 | 目标模块 | 证据数 | 代表草稿 | 人工自动应用 |", "| --- | --- | ---: | --- | --- |"]
        for item in proposals:
            keys = ", ".join(item.get("sample_case_keys") or []) or "-"
            lines.append(
                f"| {item['proposal_id']} | `{item['target_symbol']}` ({item['title']}) | {item['evidence_count']} | {keys} | 否（需人工审阅） |"
            )
        lines.append("")
        for item in proposals:
            lines.append(f"### {item['proposal_id']} · {item['title']}")
            lines.append(f"- 建议动作：{item['next_action']}")
            if item.get("redacted_corrections"):
                lines.append(f"- 脱敏用户纠正样本：{'；'.join(item['redacted_corrections'])}")
            lines.append(f"- 建议核验：`{'` / `'.join(item.get('suggested_checks') or [])}`")
            lines.append("")

    lines += ["## 3. 对照实验与门禁裁决（只读）", ""]
    if experiment.get("status") != "COMPLETED":
        reason = f"（{experiment.get('error')}）" if experiment.get("error") else ""
        lines += [f"- 实验状态：{experiment.get('status', 'NOT_RUN')}{reason}", ""]
    else:
        lines += [
            f"- 配对检验结论：**{experiment.get('verdict')}**",
            f"- 门禁裁决：**{gate.get('verdict') if gate else 'NOT_RUN'}**",
            "",
            "| 套件 | 用例数 | 改善 (`candidate_only`) | 退化 (`baseline_only`) | McNemar p | 结论 |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in experiment.get("suites") or []:
            lines.append(
                f"| {row['suite']} | {row['cases']} | {row['candidate_only']} | {row['baseline_only']} | {row['mcnemar_p']:.4f} | {row['verdict']} |"
            )
        lines.append("")

    lines += [
        "## 4. 后续人工批准入口",
        "",
        "1. 在后台“AI 回归用例”页面或通过 `POST /api/v1/ai/regression-cases/batch-review` 审核并批准 `DRAFT` 用例。",
        "2. 确认候选目录通过四套件稳定性与 McNemar 检验后，如需晋升基线，必须人工执行 `python scripts/eval_prompt_gate.py --candidate-dir <dir> --promote-baseline`。",
    ]
    return "\n".join(lines) + "\n"
