"""离线 AI 护栏评测集；不调用模型、不写数据库。"""

from types import SimpleNamespace

from app.core.errors import BusinessValidationError
from app.modules.ai.schema import (
    AIChatMessage,
    AIChatRequest,
    AIPurchaseDraftPreview,
    Intent,
    IntentResult,
)
from app.modules.ai.catalog import CATALOG
from app.modules.chemicals.cas import extract_valid_cas
from app.modules.ai.order_trace import _stage, extract_order_trace_no
from app.modules.ai.service import _format_text2sql_result
from app.modules.ai.llm import _validate_read_only_request
from app.modules.ai.text2sql import QueryPlan, _unit_metadata, build_statement


# 旧关键词分类器仅用于离线护栏回归；生产入口使用 routing.understand。

GREETING_MARKERS = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "hey",
    "在吗",
    "有人吗",
    "早上好",
    "上午好",
    "中午好",
    "下午好",
    "晚上好",
    "辛苦了",
)


PROJECT_MARKERS = (
    "你能干什么",
    "你能做什么",
    "你可以做什么",
    "你是干什么的",
    "你是做什么的",
    "你是干嘛的",
    "你是谁",
    "你是什么",
    "你会什么",
    "你的作用",
    "你的职责",
    "可以帮我什么",
    "我可以问你什么",
    "我能问你什么",
    "我可以问哪些",
    "我能问哪些",
    "可以问你什么",
    "能问你什么",
    "可以问你哪些",
    "能问你哪些",
    "可以问哪些问题",
    "能问哪些问题",
    "可以咨询什么",
    "能咨询什么",
    "能帮我什么",
    "能帮忙做什么",
    "能提供什么",
    "能解决什么问题",
    "请介绍一下你自己",
    "介绍一下你自己",
    "介绍下你自己",
    "ai能做什么",
    "ai可以做什么",
    "能做哪些事情",
    "能做哪些",
    "有什么功能",
    "有哪些功能",
    "支持哪些功能",
    "支持哪些能力",
    "支持什么",
    "项目有什么功能",
    "项目有哪些功能",
    "项目当前状态",
    "项目做到什么程度",
    "目前做到什么程度",
    "现在做到什么程度",
    "当前能做什么",
    "怎么使用",
    "如何使用",
    "使用方法",
    "使用说明",
    "操作说明",
    "功能介绍",
    "系统介绍",
    "帮助",
)


UNSUPPORTED_MARKERS = (
    "天气",
    "天气预报",
    "新闻",
    "热点",
    "热搜",
    "微博热搜",
    "股票",
    "股价",
    "基金",
    "彩票",
    "写诗",
    "作诗",
    "讲故事",
    "写小说",
    "旅游攻略",
    "旅行攻略",
    "外卖",
    "电影推荐",
    "电视剧推荐",
    "歌曲推荐",
    "唱歌",
)


QUERY_MARKERS = (
    "采购",
    "采购申请",
    "采购订单",
    "订单",
    "库存",
    "库存余额",
    "库存批次",
    "到货",
    "收货",
    "入库",
    "入库单",
    "质量",
    "质量验收",
    "验收",
    "合格",
    "不合格",
    "异常",
    "逾期",
    "财务",
    "对账",
    "发票",
    "付款",
    "结算",
    "供应商",
    "供应商数量",
    "询价",
    "查询",
    "查一下",
    "查查",
    "看一下",
    "帮我看",
    "告诉我",
    "多少",
    "数量",
    "金额",
    "总额",
    "合计",
    "统计",
    "列表",
    "明细",
    "记录",
    "排名",
    "占比",
    "平均",
    "趋势",
    "最近",
    "今年",
    "本月",
    "上月",
    "按",
    "分组",
)


DOC_MARKERS = (
    "特性",
    "性质",
    "物性",
    "特点",
    "溶解度",
    "蒸气压",
    "自燃温度",
    "密度",
    "外观",
    "粘度",
    "黏度",
    "闪点",
    "沸点",
    "熔点",
    "分子式",
    "分子量",
    "危险性",
    "危险类别",
    "危险声明",
    "信号词",
    "ghs",
    "msds",
    "sds",
    "安全数据表",
    "安全技术说明书",
    "急救",
    "消防",
    "灭火",
    "泄漏处置",
    "职业接触",
    "tlv",
    "ld50",
    "lc50",
    "毒性",
    "储存条件",
    "存储条件",
    "相容性",
    "不相容",
    "nfpa",
)


def classify_intent(text: str) -> IntentResult:
    """旧关键词分类器，仅保留离线兼容回归；生产入口统一使用 routing.understand。"""

    normalized = text.strip().lower()
    if not normalized:
        return IntentResult(Intent.UNSUPPORTED, "empty")
    if any(marker in normalized for marker in PROJECT_MARKERS):
        return IntentResult(Intent.PROJECT, "project_marker")
    if any(marker in normalized for marker in GREETING_MARKERS):
        return IntentResult(Intent.GREETING, "greeting_marker")
    if any(marker in normalized for marker in UNSUPPORTED_MARKERS):
        return IntentResult(Intent.UNSUPPORTED, "unsupported_marker")
    if extract_valid_cas(text):
        return IntentResult(Intent.DOC, "cas_pattern")
    if any(marker in normalized for marker in DOC_MARKERS):
        return IntentResult(Intent.DOC, "doc_marker")
    if any(marker in normalized for marker in QUERY_MARKERS):
        return IntentResult(Intent.QUERY, "business_query_marker")
    return IntentResult(Intent.UNSUPPORTED, "no_supported_marker")


INTENT_CASES = (
    ("greeting", "你好", Intent.GREETING),
    ("project_help", "你有什么功能", Intent.PROJECT),
    ("procurement_capability_question", "我可以问你什么采购的问题呢？", Intent.PROJECT),
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
        "intent_scope": "legacy_keyword_regression_only; current semantic routing requires scripts/evaluate_intent_routing.py",
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "accuracy": round(passed_count / len(results), 4) if results else 1.0,
        "cases": results,
    }
