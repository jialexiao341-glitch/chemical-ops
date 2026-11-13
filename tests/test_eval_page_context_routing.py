"""页面上下文消歧与能力兜底专项评测脚本单元测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.modules.ai_agent.schema import Understanding
from scripts import evaluate_page_context_routing as eval_pc
from scripts.evaluation_manifest import build_manifest


def test_build_cases_and_restricted_manifest_cover_expected_guards():
    """应构建 9 条页面上下文与权限兜底用例，并按场景准确裁剪能力清单。"""
    manifest = build_manifest("test-pc").model_dump(mode="json")
    cases = eval_pc.build_cases(manifest)

    assert [case["id"] for case in cases] == [
        "PC01", "PC02", "PC03", "PC04", "PC05", "GD01", "GD02", "GD03", "GD04",
    ]
    gd01 = next(case for case in cases if case["id"] == "GD01")
    gd02 = next(case for case in cases if case["id"] == "GD02")
    assert gd01["manifest"]["document_search"] is False
    assert manifest["document_search"] is True
    assert all(
        item.get("purpose") != "purchase_order_submit"
        for item in gd02["manifest"]["action_proposals"]
    )


def test_check_decision_verifies_route_slot_and_tasks():
    """校验函数应同时核对路由、绑定单号槽位及子任务集合。"""
    manifest = build_manifest("test-pc").model_dump(mode="json")
    cases = {case["id"]: case for case in eval_pc.build_cases(manifest)}

    ok_po = Understanding(purpose="purchase_order_submit", slots={"po_no": "PO-26001"})
    wrong_slot = Understanding(purpose="purchase_order_submit", slots={"po_no": "PO-99999"})
    assert eval_pc.check_decision(ok_po, cases["PC01"]) is True
    assert eval_pc.check_decision(wrong_slot, cases["PC01"]) is False

    ok_trace = Understanding(
        purpose="query",
        execution_mode="agent",
        tasks=["order_trace"],
        slots={"po_no": "PO-26001"},
    )
    assert eval_pc.check_decision(ok_trace, cases["PC05"]) is True


def test_evaluate_compare_mode_reports_before_and_after_totals(monkeypatch):
    """compare 模式应在隔离环境下区分改前缺失绑定与改后命中绑定。"""
    monkeypatch.setattr(eval_pc.model_catalog, "activate", lambda: None)
    monkeypatch.setattr(
        eval_pc,
        "resolve_model_profile",
        lambda _settings: SimpleNamespace(name="TestProfile", model="mock-model"),
    )

    async def fake_understand(question, context, _settings, manifest=None):
        page_context = context.get("page_context") or {}
        if page_context.get("reference_no") == "PO-26001" and page_context.get("status") == "DRAFT":
            return Understanding(purpose="purchase_order_submit", slots={"po_no": "PO-26001"})
        if page_context.get("status") == "APPROVED" and "提交" in question:
            return Understanding(purpose="unsupported", question="仅草稿可提交")
        return Understanding(
            purpose="clarify",
            clarification_slot="bill_type",
            clarification_options=["采购申请", "采购订单"],
            question="请明确单据类型",
        )

    monkeypatch.setattr(eval_pc, "understand", fake_understand)

    report = asyncio.run(eval_pc.evaluate(repeats=1, mode="compare", workers=2))
    assert report["model"] == "mock-model"
    assert report["total"] == 9
    assert report["before_total_passed"] == 0
    assert report["passed"] >= 2
