"""基于完整可比报价生成可解释的成本候选与独立风险事实。"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any


def _amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def build_quote_recommendation(
    rows: list[dict[str, Any]],
    *,
    expected_item_ids: set[int],
    truncated: bool = False,
) -> dict[str, Any]:
    """只在全部询价明细都有完整可比成本且币种一致时选出唯一成本候选。

    账期、交期与可见质量验收统计作为解释和风险事实返回，不混入金额或综合分。
    """
    empty = {
        "status": "NO_RECOMMENDATION",
        "candidate_quote_id": None,
        "candidate_supplier_id": None,
        "currency_code": None,
        "total_cost": None,
        "reasons": [],
        "risks": [],
    }
    if truncated:
        return {**empty, "reasons": ["报价结果已截断，无法确认完整候选集，不生成中选建议。"]}
    if not expected_item_ids:
        return {**empty, "reasons": ["没有可比较的询价明细，不生成中选建议。"]}

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["quote_id"])].append(row)

    eligible: list[dict[str, Any]] = []
    excluded: list[str] = []
    for quote_id, quote_rows in grouped.items():
        line_ids = {int(row["rfq_item_id"]) for row in quote_rows}
        if line_ids != expected_item_ids or len(quote_rows) != len(expected_item_ids):
            excluded.append(f"报价 {quote_id} 未完整覆盖询价明细，不参与建议。")
            continue
        if any(row.get("comparison_status") != "COMPARABLE" for row in quote_rows):
            excluded.append(f"报价 {quote_id} 含不可比明细，不参与建议。")
            continue

        currencies = {row.get("currency_code") for row in quote_rows}
        costs = [_amount((row.get("cost_analysis") or {}).get("total_cost")) for row in quote_rows]
        if len(currencies) != 1 or None in currencies:
            excluded.append(f"报价 {quote_id} 的币种信息不完整，不参与建议。")
            continue
        if any(not (row.get("cost_analysis") or {}).get("complete") for row in quote_rows) or any(
            value is None for value in costs
        ):
            excluded.append(f"报价 {quote_id} 的总成本不完整，不参与建议。")
            continue
        suppliers = {int(row["supplier_id"]) for row in quote_rows}
        if len(suppliers) != 1:
            excluded.append(f"报价 {quote_id} 的供应商信息不一致，不参与建议。")
            continue

        eligible.append({
            "quote_id": quote_id,
            "supplier_id": next(iter(suppliers)),
            "currency_code": next(iter(currencies)),
            "total_cost": sum(costs, Decimal("0")),
            "rows": quote_rows,
        })

    if not eligible:
        return {**empty, "reasons": [*excluded, "没有满足完整、可比和成本完整条件的报价。"]}

    currencies = {item["currency_code"] for item in eligible}
    if len(currencies) != 1:
        return {
            **empty,
            "reasons": [*excluded, "可比报价存在不同币种；未做汇率换算，不能跨币种比较总成本。"],
        }

    eligible.sort(key=lambda item: (item["total_cost"], item["quote_id"]))
    minimum = eligible[0]["total_cost"]
    lowest = [item for item in eligible if item["total_cost"] == minimum]
    if len(lowest) != 1:
        tied_ids = "、".join(str(item["quote_id"]) for item in lowest)
        return {
            **empty,
            "status": "TIE",
            "reasons": [*excluded, f"报价 {tied_ids} 的完整可比总成本并列，无法唯一推荐。"],
        }

    candidate = lowest[0]
    candidate_rows = candidate["rows"]
    reasons = [
        f"在 {len(eligible)} 份完整可比报价中，总成本最低为 {candidate['total_cost']} {candidate['currency_code']}。"
    ]
    risks = list(excluded)

    candidate_leads = [row.get("lead_days") for row in candidate_rows]
    all_leads = [row.get("lead_days") for item in eligible for row in item["rows"]]
    if any(value is None for value in candidate_leads):
        risks.append("候选报价有询价明细未登记交期，无法完整评估交付时间。")
    else:
        candidate_lead = max(candidate_leads)
        known_leads = [value for value in all_leads if value is not None]
        if known_leads and candidate_lead > min(known_leads):
            risks.append(
                f"候选报价最长交期为 {candidate_lead} 天；完整可比报价中最短交期为 {min(known_leads)} 天。"
            )
        elif known_leads and candidate_lead < max(known_leads):
            reasons.append(
                f"候选报价最长交期为 {candidate_lead} 天，快于其他完整可比报价的最长交期 {max(known_leads)} 天。"
            )

    terms = sorted({str(row["payment_terms"]).strip() for row in candidate_rows
                    if row.get("payment_terms") and str(row["payment_terms"]).strip()})
    if not terms:
        risks.append("候选报价未登记付款条件，账期影响未知。")
    else:
        risks.append(f"候选报价付款条件：{'；'.join(terms)}；未将资金占用折算为金额。")

    quality = candidate_rows[0].get("quality_history") or {"status": "UNKNOWN"}
    if quality.get("status") == "OBSERVED":
        sample_count = int(quality.get("sample_count") or 0)
        passed = int(quality.get("passed") or 0)
        partial = int(quality.get("partial") or 0)
        failed = int(quality.get("failed") or 0)
        risks.append(
            f"可见历史验收 {sample_count} 次：合格 {passed}、部分合格 {partial}、不合格 {failed}；仅作事实提示，不构成质量评分。"
        )
    else:
        risks.append(f"历史质量风险未知：{quality.get('reason') or '没有可用的可见验收记录'}。")

    if len(eligible) == 1:
        reasons.append("当前只有一份完整可比报价，不代表已证明其优于未纳入比较的报价。")
    if excluded:
        reasons.append("另有不完整或不可比报价已排除，详见风险提示。")

    return {
        "status": "RECOMMENDED",
        "candidate_quote_id": candidate["quote_id"],
        "candidate_supplier_id": candidate["supplier_id"],
        "currency_code": candidate["currency_code"],
        "total_cost": str(candidate["total_cost"]),
        "reasons": reasons,
        "risks": risks,
    }
