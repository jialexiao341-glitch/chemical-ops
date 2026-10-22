def _row(
    quote_id,
    supplier_id,
    item_id,
    total_cost,
    *,
    currency="CNY",
    status="COMPARABLE",
    lead_days=5,
    payment_terms="月结30天",
    quality=None,
    complete=True,
):
    return {
        "quote_id": quote_id,
        "supplier_id": supplier_id,
        "rfq_item_id": item_id,
        "currency_code": currency,
        "comparison_status": status,
        "cost_analysis": {
            "complete": complete,
            "total_cost": str(total_cost) if total_cost is not None else None,
        },
        "lead_days": lead_days,
        "payment_terms": payment_terms,
        "quality_history": quality or {"status": "UNKNOWN", "reason": "无可见历史"},
    }


def _recommend(rows, expected_item_ids, *, truncated=False):
    from app.modules.rfqs.recommendation import build_quote_recommendation

    return build_quote_recommendation(rows, expected_item_ids=expected_item_ids, truncated=truncated)


def test_recommends_unique_lowest_complete_quote_and_explains_risk_dimensions():
    rows = [
        _row(51, 8, 31, "100", lead_days=4, payment_terms="款到发货",
             quality={"status": "OBSERVED", "sample_count": 4, "passed": 4, "partial": 0, "failed": 0}),
        _row(52, 9, 31, "110", lead_days=9, payment_terms="预付30%，月结30天",
             quality={"status": "OBSERVED", "sample_count": 5, "passed": 3, "partial": 1, "failed": 1}),
    ]

    result = _recommend(rows, {31})

    assert result["status"] == "RECOMMENDED"
    assert result["candidate_quote_id"] == 51
    assert result["total_cost"] == "100"
    assert result["currency_code"] == "CNY"
    assert any("总成本最低" in reason for reason in result["reasons"])
    assert any("交期" in reason and "4" in reason and "9" in reason for reason in result["reasons"])
    assert any("款到发货" in risk for risk in result["risks"])
    assert any("4" in risk and "合格" in risk for risk in result["risks"])


def test_aggregates_all_lines_before_choosing_quote():
    rows = [
        _row(51, 8, 31, "10"),
        _row(51, 8, 32, "90"),
        _row(52, 9, 31, "70"),
        _row(52, 9, 32, "20"),
    ]

    result = _recommend(rows, {31, 32})

    assert result["candidate_quote_id"] == 52
    assert result["total_cost"] == "90"


def test_does_not_recommend_when_quote_is_incomplete_or_not_comparable():
    rows = [
        _row(51, 8, 31, "100"),
        _row(52, 9, 31, "50", complete=False),
        _row(53, 10, 31, "40", status="NOT_COMPARABLE"),
    ]

    result = _recommend(rows, {31})

    assert result["candidate_quote_id"] == 51
    assert result["total_cost"] == "100"
    assert any("不参与建议" in risk for risk in result["risks"])


def test_does_not_compare_currencies_or_choose_between_tied_costs():
    currency_result = _recommend(
        [_row(51, 8, 31, "100", currency="CNY"), _row(52, 9, 31, "90", currency="USD")], {31}
    )
    tied_result = _recommend([_row(51, 8, 31, "100"), _row(52, 9, 31, "100")], {31})

    assert currency_result["status"] == "NO_RECOMMENDATION"
    assert currency_result["candidate_quote_id"] is None
    assert any("币种" in reason for reason in currency_result["reasons"])
    assert tied_result["status"] == "TIE"
    assert tied_result["candidate_quote_id"] is None


def test_does_not_recommend_when_any_requested_line_is_missing_or_result_is_truncated():
    missing_line = _recommend([_row(51, 8, 31, "100")], {31, 32})
    truncated = _recommend([_row(51, 8, 31, "100")], {31}, truncated=True)

    assert missing_line["status"] == "NO_RECOMMENDATION"
    assert missing_line["candidate_quote_id"] is None
    assert truncated["status"] == "NO_RECOMMENDATION"
    assert truncated["candidate_quote_id"] is None
