"""用当前配置的模型和开发库执行只读问法回归。"""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import BusinessValidationError
from app.modules.ai.text2sql import QueryPlan, Text2SQLRequest, run_text2sql
from app.modules.ai.structured import schema_response_format
from app.modules.ai.routing import understand
from app.modules.system.model import User


CASES = (
    ("统计本月已付款金额，按供应商分组", "finance_payments", "amount", "supplier", ("status", "PAID")),
    ("统计已核验发票含税金额，按供应商分组", "finance_invoices", "amount", "supplier", ("status", "VERIFIED")),
    ("按供应商统计报价单笔数", "supplier_quotes", "count", "supplier", None),
    ("按类型统计库存流水笔数", "inventory_transactions", "count", "type", None),
    ("按供应商统计采购订单金额", "purchase_orders", "amount", "supplier", None),
    ("按验收结果统计质量验收单数量", "quality_acceptances", "count", "result", None),
    ("按状态统计运营异常数量", "exceptions", "count", "status", None),
    ("按供应商统计到货单数量", "deliveries", "count", "supplier", None),
)
UNSUPPORTED_CASES = ("统计供应商报价金额合计", "统计库存流水数量合计")

# 独立 SQL 真值，不调用被测计划生成器或 SQL 构造器。
ORACLES = {
    "finance_payments": "SELECT s.supplier_name AS supplier, p.currency_code AS currency, SUM(p.amount) AS metric_value FROM finance_payments p JOIN suppliers s ON s.id=p.supplier_id WHERE p.status='PAID' AND p.paid_at>=:month_start AND p.paid_at<:next_month GROUP BY s.supplier_name,p.currency_code",
    "finance_invoices": "SELECT s.supplier_name AS supplier, i.currency_code AS currency, SUM(i.amount_incl_tax) AS metric_value FROM finance_invoices i JOIN suppliers s ON s.id=i.supplier_id WHERE i.status='VERIFIED' GROUP BY s.supplier_name,i.currency_code",
    "supplier_quotes": "SELECT s.supplier_name AS supplier, COUNT(q.id) AS metric_value FROM supplier_quotes q JOIN suppliers s ON s.id=q.supplier_id JOIN rfqs r ON r.id=q.rfq_id GROUP BY s.supplier_name",
    "inventory_transactions": "SELECT transaction_type AS type,COUNT(id) AS metric_value FROM inventory_transactions GROUP BY transaction_type",
    "purchase_orders": "SELECT s.supplier_name AS supplier,p.currency_code AS currency,SUM(p.order_amount) AS metric_value FROM purchase_orders p JOIN suppliers s ON s.id=p.supplier_id GROUP BY s.supplier_name,p.currency_code",
    "quality_acceptances": "SELECT result,COUNT(id) AS metric_value FROM quality_acceptances GROUP BY result",
    "exceptions": "SELECT status,COUNT(id) AS metric_value FROM operation_exceptions GROUP BY status",
    "deliveries": "SELECT s.supplier_name AS supplier,COUNT(d.id) AS metric_value FROM deliveries d JOIN suppliers s ON s.id=d.supplier_id JOIN purchase_orders p ON p.id=d.po_id GROUP BY s.supplier_name",
}


def comparable(rows):
    def value(item):
        if item is not None and re.fullmatch(r"-?\d+(\.\d+)?", str(item)):
            return format(Decimal(str(item)).normalize(), "f")
        return item
    return sorted(json.dumps({key: value(item) for key, item in row.items()}, ensure_ascii=False, sort_keys=True) for row in rows)


def execution_matches(plan, actual, expected, truncated):
    """核对授权全集的聚合值与前 N 项；并列项不要求数据库返回固定顺序。"""
    count = min(plan.limit, len(expected))
    if len(actual) != count or truncated != (len(expected) > plan.limit):
        return False
    if not set(comparable(actual)) <= set(comparable(expected)) or len(set(comparable(actual))) != len(actual):
        return False
    if not actual:
        return True
    metrics = sorted((Decimal(str(row["metric_value"] or 0)) for row in expected), reverse=plan.order == "desc")
    observed = [Decimal(str(row["metric_value"] or 0)) for row in actual]
    return observed == sorted(observed, reverse=plan.order == "desc") and sorted(observed) == sorted(metrics[:count])


async def main(output: Path | None = None) -> int:
    settings = get_settings()
    if settings.app_env != "development" or not settings.openai_api_key:
        raise SystemExit("只在已配置模型的开发环境运行")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == "system_admin"))
        if user is None:
            raise SystemExit("缺少用于只读评估的管理员账号")
        results = []
        for question, dataset, metric, group_by, required_filter in CASES:
            recognized = False
            try:
                recognized = (await understand(question, settings=settings)).route == "query"
                # 这些样本的业务意图由评测集预先标注；独立测计划和执行，避免识别失败掩盖规划结果。
                response = await run_text2sql(db, user, Text2SQLRequest(question=question, limit=100), settings, intent_verified=True)
                plan = response.plan
                matched_filter = required_filter is None or any(
                    item.field == required_filter[0] and item.operator == "eq" and item.value == required_filter[1]
                    for item in plan.filters
                )
                passed = (plan.dataset, plan.metric, plan.group_by) == (dataset, metric, group_by) and matched_filter
                if dataset == "finance_payments":
                    passed = passed and plan.time_field == "paid_at" and plan.date_from == date.today().replace(day=1)
                first = date.today().replace(day=1)
                next_month = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
                expected = [dict(row) for row in db.execute(text(ORACLES[dataset]), {"month_start": first, "next_month": next_month}).mappings()]
                execution_passed = execution_matches(plan, response.rows, expected, response.truncated)
                results.append({"question": question, "passed": recognized and passed and execution_passed,
                                "recognition_passed": recognized,
                                "plan_passed": passed, "execution_passed": execution_passed,
                                "expected_rows": expected, "actual_rows": response.rows,
                                "dataset": plan.dataset, "metric": plan.metric,
                                "group_by": plan.group_by, "filters": [item.model_dump() for item in plan.filters],
                                "row_count": response.row_count, "truncated": response.truncated, "unit": response.unit})
            except Exception as exc:
                results.append({"question": question, "passed": False, "recognition_passed": recognized,
                                "error": type(exc).__name__, "message": str(exc)})
        for question in UNSUPPORTED_CASES:
            try:
                await run_text2sql(db, user, Text2SQLRequest(question=question), settings, intent_verified=True)
                results.append({"question": question, "passed": False, "error": "未拒绝不支持的指标"})
            except BusinessValidationError as exc:
                results.append({"question": question, "passed": "不支持" in str(exc), "result": "明确拒绝不支持的汇总"})
        report = {"model": settings.llm_model, "case_count": len(results),
                  "query_plan_schema_sha256": hashlib.sha256(json.dumps(schema_response_format(QueryPlan, "query_plan"), ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                  "passed_count": sum(item["passed"] for item in results),
                  "recognition": {"total": len(CASES), "passed": sum(item.get("recognition_passed", False) for item in results)},
                  "plan": {"total": len(CASES), "passed": sum(item.get("plan_passed", False) for item in results)},
                  "execution": {"total": len(CASES), "passed": sum(item.get("execution_passed", False) for item in results)},
                  "scope": "开发库管理员只读查询；识别独立评分，计划与执行使用评测集已标注的业务查询意图；独立 SQL 核验聚合与前 N 项，不代表跨角色、回答质量或生产效果", "cases": results}
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
            print(json.dumps({key: value for key, value in report.items() if key not in {"cases", "scope"}}))
        else:
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        return 0 if all(item["passed"] for item in results) else 1
    finally:
        db.close()


async def repeated(output: Path, repeats: int) -> int:
    reports = []
    for number in range(1, repeats + 1):
        path = output.with_name(f"{output.stem}-round{number}{output.suffix}")
        await main(path)
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    report = {"model": reports[0]["model"], "repeats": repeats,
              "sample_count": reports[0]["case_count"],
              "case_count": sum(item["case_count"] for item in reports),
              "passed_count": sum(item["passed_count"] for item in reports),
              "query_plan_schema_sha256": reports[0]["query_plan_schema_sha256"],
              "scope": reports[0]["scope"],
              "rounds": reports}
    for phase in ("recognition", "plan", "execution"):
        report[phase] = {key: sum(item[phase][key] for item in reports) for key in ("total", "passed")}
    report["stable_cases"] = sum(all(item["cases"][index]["passed"] for item in reports)
                                 for index in range(report["sample_count"]))
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"rounds", "scope"}}))
    return int(report["passed_count"] != report["case_count"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    args = parser.parse_args()
    if args.repeats > 1 and args.output is None:
        parser.error("重复评测需要 --output 保存每轮证据")
    raise SystemExit(asyncio.run(main(args.output) if args.repeats == 1 else repeated(args.output, args.repeats)))
