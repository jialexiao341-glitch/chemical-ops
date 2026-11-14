"""页面上下文消歧与能力/状态硬约束独立评测脚本；不改动 34 条主路由基线题集。"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.modules.ai_agent.agent_execution import routing  # noqa: E402
from app.modules.ai_agent.agent_execution.routing import ROUTING_PROMPT, understand  # noqa: E402
from app.modules.ai_agent.model_access import model_catalog  # noqa: E402
from app.modules.ai_agent.model_access.gateway import resolve_model_profile  # noqa: E402
from scripts.eval_runtime_common import eval_llm_settings, exception_run_meta  # noqa: E402
from scripts.evaluation_manifest import build_manifest  # noqa: E402


def restricted_manifest(
    base: dict,
    *,
    drop_purposes: set[str] | None = None,
    disable_document: bool = False,
) -> dict:
    """按权限场景裁剪能力清单副本，用于验证服务端能力硬约束。"""
    payload = json.loads(json.dumps(base))
    if drop_purposes:
        payload["action_proposals"] = [
            item
            for item in payload.get("action_proposals", [])
            if item.get("purpose") not in drop_purposes
        ]
    if disable_document:
        payload["document_search"] = False
    return payload


def build_cases(full_manifest: dict) -> list[dict]:
    """构造 9 条页面上下文指代消歧与能力/状态硬约束用例。"""
    return [
        {
            "id": "PC01",
            "group": "page_context_disambiguation",
            "label": "采购订单草稿页：提交审批",
            "question": "把这张单子提交审批",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_order",
                    "reference_no": "PO-26001",
                    "status": "DRAFT",
                    "title": "采购订单 PO-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "purchase_order_submit",
            "expected_slot": ("po_no", "PO-26001"),
            "expected_tasks": None,
        },
        {
            "id": "PC02",
            "group": "page_context_disambiguation",
            "label": "采购申请草稿页：提交审批",
            "question": "把这张单子提交审批",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_request",
                    "reference_no": "PR-26001",
                    "status": "DRAFT",
                    "title": "采购申请 PR-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "purchase_submit",
            "expected_slot": ("request_no", "PR-26001"),
            "expected_tasks": None,
        },
        {
            "id": "PC03",
            "group": "page_context_disambiguation",
            "label": "采购申请草稿页：修改预算",
            "question": "把申请单的预算改成 5000 元",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_request",
                    "reference_no": "PR-26001",
                    "status": "DRAFT",
                    "title": "采购申请 PR-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "purchase_update",
            "expected_slot": ("request_no", "PR-26001"),
            "expected_tasks": None,
        },
        {
            "id": "PC04",
            "group": "page_context_disambiguation",
            "label": "已审批采购申请页：创建询价",
            "question": "给供应商 SUP-001 创建询价草稿",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_request",
                    "reference_no": "PR-26002",
                    "status": "APPROVED",
                    "title": "采购申请 PR-26002",
                },
            },
            "manifest": full_manifest,
            "expected_route": "rfq_draft",
            "expected_slot": ("request_no", "PR-26002"),
            "expected_tasks": None,
        },
        {
            "id": "PC05",
            "group": "page_context_disambiguation",
            "label": "采购订单详情页：跟踪进度",
            "question": "跟踪一下这单进度",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_order",
                    "reference_no": "PO-26001",
                    "status": "APPROVING",
                    "title": "采购订单 PO-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "agent",
            "expected_slot": ("po_no", "PO-26001"),
            "expected_tasks": ["order_trace"],
        },
        {
            "id": "GD01",
            "group": "capability_and_state_guard",
            "label": "关闭资料检索时询问化学品闪点（权限兜底）",
            "question": "乙醇的闪点是多少",
            "before_context": {},
            "after_context": {},
            "manifest": restricted_manifest(full_manifest, disable_document=True),
            "expected_route": "unsupported",
            "expected_slot": None,
            "expected_tasks": None,
        },
        {
            "id": "GD02",
            "group": "capability_and_state_guard",
            "label": "无订单提交权限时请求提交订单（权限兜底）",
            "question": "把采购订单 PO20261004004266 提交审批",
            "before_context": {},
            "after_context": {},
            "manifest": restricted_manifest(full_manifest, drop_purposes={"purchase_order_submit"}),
            "expected_route": "unsupported",
            "expected_slot": None,
            "expected_tasks": None,
        },
        {
            "id": "GD03",
            "group": "capability_and_state_guard",
            "label": "已审批订单页请求提交审批（状态兜底）",
            "question": "把采购订单 PO-26001 提交审批",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_order",
                    "reference_no": "PO-26001",
                    "status": "APPROVED",
                    "title": "采购订单 PO-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "unsupported",
            "expected_slot": None,
            "expected_tasks": None,
        },
        {
            "id": "GD04",
            "group": "capability_and_state_guard",
            "label": "草稿采购申请页请求创建询价（状态兜底）",
            "question": "根据采购申请 PR-26001 给供应商 SUP-001 创建询价草稿",
            "before_context": {},
            "after_context": {
                "page_context": {
                    "object_type": "purchase_request",
                    "reference_no": "PR-26001",
                    "status": "DRAFT",
                    "title": "采购申请 PR-26001",
                },
            },
            "manifest": full_manifest,
            "expected_route": "unsupported",
            "expected_slot": None,
            "expected_tasks": None,
        },
    ]


def check_decision(decision: routing.Understanding, case: dict) -> bool:
    """校验路由结果是否满足预期路线、关键单号槽位与子任务类型。"""
    if decision.route != case["expected_route"]:
        return False
    if case["expected_tasks"] is not None and set(decision.tasks) != set(case["expected_tasks"]):
        return False
    if case["expected_slot"] is not None:
        slot_name, slot_val = case["expected_slot"]
        if getattr(decision.slots, slot_name, None) != slot_val:
            return False
    return True


async def _run_case(
    case: dict,
    *,
    mode: str,
    round_idx: int,
    settings,
    sem: asyncio.Semaphore,
) -> dict:
    """执行单条用例并记录错误分类与耗时，compare 模式下模拟改前链路。"""
    async with sem:
        t0 = perf_counter()
        orig_guard = routing._apply_capability_and_context_guards
        orig_bind = routing._bind_page_context_slots
        try:
            if mode == "before":
                routing._apply_capability_and_context_guards = lambda decision, **_kwargs: decision
                routing._bind_page_context_slots = lambda content, _ctx: content
                ctx = case["before_context"]
            else:
                ctx = case["after_context"]
            decision = await understand(case["question"], ctx, settings, manifest=case["manifest"])
            return {
                "id": case["id"],
                "group": case["group"],
                "label": case["label"],
                "mode": mode,
                "round": round_idx,
                "passed": check_decision(decision, case),
                "route": decision.route,
                "tasks": decision.tasks,
                "slots": decision.slots.model_dump(mode="json"),
                "seconds": round(perf_counter() - t0, 2),
            }
        except Exception as exc:
            run_meta = exception_run_meta(exc, default_infra_code="INTENT_SERVICE_ERROR")
            return {
                "id": case["id"],
                "group": case["group"],
                "label": case["label"],
                "mode": mode,
                "round": round_idx,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "evaluation_error_code": getattr(exc, "code", None),
                "error_class": (run_meta.get("error") or {}).get("class") or "UNKNOWN",
                "run_meta": run_meta,
                "seconds": round(perf_counter() - t0, 2),
            }
        finally:
            routing._apply_capability_and_context_guards = orig_guard
            routing._bind_page_context_slots = orig_bind


async def evaluate(*, repeats: int = 3, mode: str = "eval", workers: int = 3) -> dict:
    """运行页面上下文与能力兜底专项评测，支持纯回归（eval）和前后对照（compare）。"""
    model_catalog.activate()
    settings = eval_llm_settings(get_settings(), min_timeout_seconds=120)
    profile = resolve_model_profile(settings)
    full_manifest = build_manifest("page-context-routing-eval").model_dump(mode="json")
    cases = build_cases(full_manifest)
    sem = asyncio.Semaphore(workers)

    modes = ("before", "after") if mode == "compare" else ("after",)
    rows: list[dict] = []
    # compare 模式按轮串行切换模块钩子，避免并发 monkeypatch 污染。
    for round_idx in range(1, repeats + 1):
        for current_mode in modes:
            if mode == "compare":
                for case in cases:
                    rows.append(
                        await _run_case(case, mode=current_mode, round_idx=round_idx, settings=settings, sem=sem),
                    )
            else:
                rows.extend(
                    await asyncio.gather(
                        *(
                            _run_case(case, mode=current_mode, round_idx=round_idx, settings=settings, sem=sem)
                            for case in cases
                        ),
                    ),
                )

    summary = []
    for case in cases:
        after_rows = [r for r in rows if r["id"] == case["id"] and r["mode"] == "after"]
        entry = {
            "id": case["id"],
            "group": case["group"],
            "label": case["label"],
            "passed": sum(int(r["passed"]) for r in after_rows),
            "rounds": repeats,
            "routes": [r.get("route") or r.get("error") for r in after_rows],
        }
        if mode == "compare":
            before_rows = [r for r in rows if r["id"] == case["id"] and r["mode"] == "before"]
            entry["before_passed"] = sum(int(r["passed"]) for r in before_rows)
            entry["before_routes"] = [r.get("route") or r.get("error") for r in before_rows]
        summary.append(entry)

    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "model": profile.model,
        "model_profile": profile.name,
        "prompt_sha256": hashlib.sha256(ROUTING_PROMPT.encode()).hexdigest(),
        "repeats": repeats,
        "sample_count": len(cases),
        "total": len(cases) * repeats,
        "passed": sum(entry["passed"] for entry in summary),
        "summary": summary,
        "cases": rows,
    }
    if mode == "compare":
        report["before_total_passed"] = sum(entry["before_passed"] for entry in summary)
    return report


def main() -> None:
    """解析命令行参数并输出页面上下文专项评测报告。"""
    parser = argparse.ArgumentParser(description="页面上下文消歧与能力/状态硬约束专项评测")
    parser.add_argument("--mode", choices=("eval", "compare"), default="eval")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evaluation/page-context-routing.json"),
    )
    args = parser.parse_args()
    report = asyncio.run(evaluate(repeats=args.repeats, mode=args.mode, workers=args.workers))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = {
        "mode": report["mode"],
        "model": report["model"],
        "passed": f"{report['passed']}/{report['total']}",
        "output": str(args.output),
    }
    if args.mode == "compare":
        digest["before"] = f"{report['before_total_passed']}/{report['total']}"
    print(json.dumps(digest, ensure_ascii=False))


if __name__ == "__main__":
    main()
