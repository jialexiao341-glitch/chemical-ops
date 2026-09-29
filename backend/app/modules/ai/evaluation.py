"""离线 AI 护栏评测集；不调用模型、不写数据库。"""

from types import SimpleNamespace

from app.core.errors import BusinessValidationError
from app.modules.ai.catalog import CATALOG
from app.modules.ai.intent import Intent, classify_intent
from app.modules.ai.order_trace import _stage, extract_order_trace_no
from app.modules.ai.schema import AIChatMessage, AIChatRequest, AIPurchaseDraftPreview
from app.modules.ai.service import _format_text2sql_result, _validate_read_only_request
from app.modules.ai.text2sql import QueryPlan, _unit_metadata, build_statement


INTENT_CASES = (
    ("greeting", "你好", Intent.GREETING),
    ("project_help", "你有什么功能", Intent.PROJECT),
    ("purchase_query", "查询本月采购订单金额", Intent.QUERY),
    ("delivery_query", "本周哪些到货逾期", Intent.QUERY),
    ("inventory_query", "乙醇各仓库批次库存", Intent.QUERY),
    ("chemical_document", "乙醇的闪点是多少", Intent.DOC),
    ("cas_document", "CAS 64-17-5 的危险性信号词", Intent.DOC),
    ("weather_outside_scope", "今天杭州天气怎么样", Intent.UNSUPPORTED),
    ("writing_outside_scope", "给我写一首歌", Intent.UNSUPPORTED),
    ("ambiguous_follow_up", "这个怎么回事", Intent.UNSUPPORTED),
)

TRACE_CASES = (
    ("explicit_trace", "订单 PO-26001 为什么还没有结算？", "PO-26001"),
    ("order_number_only", "查询订单 PO-26001", None),
    ("missing_order_number", "为什么订单还没有结算", None),
)

WRITE_GUARD_CASES = (
    ("read_query_allowed", "查询本月采购订单数量", False),
    ("create_request_blocked", "帮我创建采购申请", True),
    ("payment_blocked", "直接帮我付款", True),
)

CATALOG_CASES = (
    ("purchase_order_amount", "purchase_orders", "amount", "order_date"),
    ("inventory_quantity", "inventory", "sum_quantity", "created_at"),
    ("reconciliation_count", "finance_reconciliations", "count", "created_at"),
    ("quality_count", "quality_acceptances", "count", "inspection_time"),
    ("quote_count", "supplier_quotes", "count", "quote_date"),
    ("inventory_movement_count", "inventory_transactions", "count", "created_at"),
    ("invoice_amount", "finance_invoices", "amount", "invoice_date"),
    ("payment_amount", "finance_payments", "amount", "paid_at"),
)


def _case(category: str, name: str, passed: bool) -> dict[str, object]:
    return {"category": category, "name": name, "passed": passed}


def run_offline_evaluation() -> dict[str, object]:
    """运行固定规则、目录、单位、引用隐私和写保护用例。"""

    results: list[dict[str, object]] = []
    for name, question, expected in INTENT_CASES:
        results.append(_case("intent", name, classify_intent(question).intent is expected))

    for name, question, expected in TRACE_CASES:
        results.append(_case("order_trace_routing", name, extract_order_trace_no(question) == expected))

    for name, question, should_block in WRITE_GUARD_CASES:
        blocked = False
        try:
            _validate_read_only_request(AIChatRequest(messages=[AIChatMessage(role="user", content=question)]))
        except BusinessValidationError:
            blocked = True
        results.append(_case("write_guard", name, blocked is should_block))

    for name, dataset, metric, time_field in CATALOG_CASES:
        spec = CATALOG.get(dataset)
        if spec is None or metric not in spec.metrics or time_field not in spec.times:
            passed = False
        else:
            try:
                statement = build_statement(QueryPlan(dataset=dataset, metric=metric, time_field=time_field, limit=5))
                passed = statement is not None
            except (BusinessValidationError, ValueError):
                passed = False
        results.append(_case("catalog_plan", name, passed))

    denied = _stage("发票", False, [{"number": "INV-PRIVATE", "amount": "999"}], summary="找到 1 条记录")
    results.append(
        _case(
            "permission_redaction",
            "unauthorized_finance_rows_removed",
            denied["status"] == "NO_PERMISSION" and denied["records"] == [] and "INV-PRIVATE" not in denied["summary"],
        )
    )

    order_plan = QueryPlan(dataset="purchase_orders", metric="amount")
    amount_unit, amount_note = _unit_metadata(order_plan, [{"currency": "CNY"}, {"currency": "USD"}])
    inventory_unit, inventory_note = _unit_metadata(
        QueryPlan(dataset="inventory_by_batch", metric="records"), [{"unit": "升"}, {"unit": "千克"}]
    )
    results.append(_case("unit_currency", "mixed_currency_not_merged", amount_unit == "多币种" and "不能合并" in (amount_note or "")))
    results.append(_case("unit_currency", "batch_units_remain_per_row", inventory_unit == "各行所示单位" and "逐行" in (inventory_note or "")))

    fallback = _format_text2sql_result(
        SimpleNamespace(
            rows=[{"supplier": "甲公司", "metric_value": "1200"}],
            render_columns=[{"key": "supplier", "label": "供应商"}, {"key": "metric_value", "label": "金额"}],
            unit="CNY",
            unit_note=None,
            row_count=1,
            truncated=False,
            plan=SimpleNamespace(limit=20),
        )
    )
    results.append(_case("numeric_fallback", "currency_present_in_template_answer", "CNY" in fallback and "1200" in fallback))
    results.append(_case("draft_safety", "preview_requires_confirmation", AIPurchaseDraftPreview.model_fields["requires_user_confirmation"].default is True))

    passed_count = sum(bool(item["passed"]) for item in results)
    return {
        "suite": "chemicalops-ai-offline-v1",
        "mode": "deterministic_no_llm_no_writes",
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "accuracy": round(passed_count / len(results), 4) if results else 1.0,
        "cases": results,
    }
