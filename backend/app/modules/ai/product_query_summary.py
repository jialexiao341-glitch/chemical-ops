"""库存与报价工具证据的确定性汇总和摘要。"""
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any


def inventory_totals(results: Sequence[Mapping[str, Any]]) -> dict[tuple[int, str], Decimal]:
    """只合计工具返回的 totals，不从受限明细行重算。"""
    totals: dict[tuple[int, str], Decimal] = {}
    for entry in results:
        if entry.get("tool") != "inventory.query_available":
            continue
        result = entry.get("result", entry)
        for row in result.get("totals", []):
            key = (row["unit_id"], row["unit_name"])
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(row["available_quantity"]))
    return totals


def summarize_product_evidence(entries: Sequence[Mapping[str, Any]]) -> str:
    """从产品库存/报价证据生成稳定摘要，不推断工具结果之外的数字。"""
    lines: list[str] = []
    inventory = [entry.get("result", entry) for entry in entries
                 if entry.get("tool") == "inventory.query_available"]
    totals = inventory_totals(entries) if inventory else {}
    if len(inventory) > 1:
        amounts = "、".join(f"{value.normalize():f} {unit}" for (_, unit), value in totals.items())
        lines.append(f"查到这 {len(inventory)} 个规格的可用库存合计为 {amounts}。下面是各规格的库存明细。" if amounts else
                     f"查询了这 {len(inventory)} 个规格，暂时没有找到库存记录。")
    for entry in entries:
        result = entry.get("result", entry)
        tool = entry["tool"]
        if tool == "inventory.query_available":
            amounts = "、".join(f"{Decimal(str(row['available_quantity'])).normalize():f} {row['unit_name']}"
                                for row in result.get("totals", []))
            label = f"{result['product_name']}（规格 #{result['product_id']}）" if len(inventory) > 1 else result['product_name']
            lines.append(f"{label}：可用库存为 {amounts}。" if amounts else f"{label}：暂时没有找到库存记录。")
        elif tool == "supplier_quotes.compare":
            lines.append(f"询价 {result['rfq_no']}：找到 {result['total_rows']} 条符合条件的最新报价。")
            recommendation = result.get("recommendation") or {}
            candidate_id = recommendation.get("candidate_quote_id")
            if recommendation.get("status") == "RECOMMENDED" and candidate_id is not None:
                candidate = next((row for row in result.get("rows", [])
                                  if row.get("quote_id") == candidate_id), None)
                if candidate:
                    name = candidate.get("supplier_name") or f"供应商 #{candidate.get('supplier_id', '-') }"
                    quote_no = candidate.get("quote_no") or f"报价 #{candidate_id}"
                    lines.append(
                        f"成本候选：{name}（{quote_no}），总成本 {recommendation['total_cost']} "
                        f"{recommendation['currency_code']}。理由：{'；'.join(recommendation.get('reasons') or [])}"
                    )
                else:
                    lines.append(f"成本候选报价 #{candidate_id}，总成本 {recommendation['total_cost']} {recommendation['currency_code']}。")
            elif recommendation.get("status") in {"TIE", "NO_RECOMMENDATION"}:
                lines.append("未生成唯一成本候选：" + "；".join(recommendation.get("reasons") or ["完整可比报价不足"]) + "。")
            for risk in recommendation.get("risks") or []:
                lines.append(f"候选核查提示：{risk}")
            for row in result.get("rows", []):
                summary = (f"{row['supplier_name']}：{row['unit_price']} {row['currency_code']}/{row['unit_name']}"
                           f"，可比组单价排名 {row['rank'] if row['rank'] is not None else '不排序'}。")
                costs = row.get("cost_analysis")
                if costs:
                    if costs.get("complete") and costs.get("total_cost") is not None:
                        summary += (f"按采购量 {costs['purchase_quantity']} {row['unit_name']} 计算的总成本为 "
                                    f"{costs['total_cost']} {row['currency_code']}（含商品税和已登记运费）；"
                                    f"MOQ 增加采购量 {costs['moq_extra_quantity']} {row['unit_name']}。")
                    else:
                        summary += "总成本尚不完整：" + "；".join(costs.get("reasons") or ["缺少成本组成信息"]) + "。"
                lines.append(summary)
        elif tool in {"catalog.search_products", "supplier_quotes.find_rfq_items"} and result.get("total_rows", 0) == 0:
            lines.append("暂时没有找到匹配的产品或询价明细，请核对名称或单号。")
        if result.get("truncated"):
            lines.append("下方明细仅展示部分记录，库存合计仍包含全部匹配记录。" if tool == "inventory.query_available"
                         else "下方仅展示部分报价记录。")
    if len(totals) > 1:
        lines.append("库存使用不同计量单位，以下分别列出，不直接相加。")
    return "\n".join(dict.fromkeys(lines))
