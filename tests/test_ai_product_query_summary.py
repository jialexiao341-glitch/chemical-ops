from decimal import Decimal

from app.modules.ai.product_query_summary import inventory_totals, summarize_product_evidence


def test_inventory_totals_group_by_unit_and_use_complete_tool_totals():
    evidence = [
        {"tool": "inventory.query_available", "totals": [
            {"unit_id": 1, "unit_name": "千克", "available_quantity": "12.5"}],
         "rows": [{"available_quantity": "999"}], "truncated": True,
         "product_name": "乙醇", "product_id": 1},
        {"tool": "inventory.query_available", "result": {"totals": [
            {"unit_id": 2, "unit_name": "升", "available_quantity": "3"}],
            "product_name": "乙醇", "product_id": 2}},
    ]

    assert inventory_totals(evidence) == {(1, "千克"): Decimal("12.5"), (2, "升"): Decimal("3")}
    summary = summarize_product_evidence(evidence)
    assert "12.5 千克" in summary and "3 升" in summary
    assert "不直接相加" in summary
    assert "部分记录" in summary
    assert "999" not in summary


def test_single_product_with_multiple_units_is_not_described_as_a_sum():
    summary = summarize_product_evidence([{
        "tool": "inventory.query_available", "product_name": "乙醇", "product_id": 1,
        "totals": [
            {"unit_id": 1, "unit_name": "千克", "available_quantity": "12.5"},
            {"unit_id": 2, "unit_name": "升", "available_quantity": "3"},
        ],
    }])

    assert "12.5 千克、3 升" in summary
    assert "不直接相加" in summary


def test_quote_summary_preserves_quote_values_and_no_result_state():
    evidence = [
        {"tool": "supplier_quotes.compare", "rfq_no": "RFQ-1", "total_rows": 2,
         "rows": [{"supplier_name": "甲", "unit_price": "8.25", "currency_code": "CNY",
                   "unit_name": "千克", "rank": 1}], "truncated": False},
        {"tool": "supplier_quotes.find_rfq_items", "total_rows": 0, "rows": [], "truncated": False},
    ]

    summary = summarize_product_evidence(evidence)
    assert "询价 RFQ-1：找到 2 条" in summary
    assert "甲：8.25 CNY/千克" in summary
    assert "没有找到匹配的产品或询价明细" in summary


def test_quote_summary_preserves_cost_completeness_and_currency():
    base = {"supplier_name": "甲", "unit_price": "8.25", "currency_code": "CNY", "unit_name": "千克", "rank": 1}
    rows = [{**base, "cost_analysis": {"complete": True, "total_cost": "121.20", "purchase_quantity": "12", "moq_extra_quantity": "2"}},
            {**base, "supplier_name": "乙", "currency_code": "USD", "cost_analysis": {"complete": False, "reasons": ["运费未登记"]}}]
    summary = summarize_product_evidence([{"tool": "supplier_quotes.compare", "rfq_no": "TEST-RFQ", "total_rows": 2, "rows": rows}])
    assert "121.20 CNY" in summary and "MOQ 增加采购量 2 千克" in summary
    assert "总成本尚不完整：运费未登记" in summary
    assert "121.20 USD" not in summary


def test_quote_summary_explains_cost_candidate_and_keeps_risks_separate():
    summary = summarize_product_evidence([{
        "tool": "supplier_quotes.compare", "rfq_no": "RFQ-2", "total_rows": 2,
        "recommendation": {
            "status": "RECOMMENDED", "candidate_quote_id": 51,
            "currency_code": "CNY", "total_cost": "100.00",
            "reasons": ["在 2 份完整可比报价中，总成本最低为 100.00 CNY。"],
            "risks": ["付款条件为：月结30天；未将资金占用折算为金额。", "历史质量风险未知：无质量权限。"],
        },
        "rows": [
            {"quote_id": 51, "quote_no": "Q-51", "supplier_name": "甲供应商",
             "unit_price": "10.00", "currency_code": "CNY", "unit_name": "千克", "rank": 1}
        ],
    }])

    assert "成本候选：甲供应商（Q-51）" in summary
    assert "100.00 CNY" in summary
    assert "未将资金占用折算为金额" in summary
    assert "历史质量风险未知" in summary


def test_quote_summary_does_not_name_a_candidate_when_analysis_is_tied():
    summary = summarize_product_evidence([{
        "tool": "supplier_quotes.compare", "rfq_no": "RFQ-3", "total_rows": 2,
        "recommendation": {
            "status": "TIE", "candidate_quote_id": None, "reasons": ["两个报价总成本并列。"], "risks": []
        },
        "rows": [
            {"quote_id": 51, "quote_no": "Q-51", "supplier_name": "甲", "unit_price": "10", "currency_code": "CNY", "unit_name": "千克", "rank": 1}
        ],
    }])

    assert "两个报价总成本并列。" in summary
    assert "成本候选：甲（Q-51）" not in summary
