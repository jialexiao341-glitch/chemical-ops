"""用当前配置的模型和开发库执行只读问法回归。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import BusinessValidationError
from app.modules.ai.text2sql import Text2SQLRequest, run_text2sql
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


async def main() -> int:
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
            try:
                response = await run_text2sql(db, user, Text2SQLRequest(question=question, limit=100), settings)
                plan = response.plan
                matched_filter = required_filter is None or any(
                    item.field == required_filter[0] and item.operator == "eq" and item.value == required_filter[1]
                    for item in plan.filters
                )
                passed = (plan.dataset, plan.metric, plan.group_by) == (dataset, metric, group_by) and matched_filter
                if dataset == "finance_payments":
                    passed = passed and plan.time_field == "paid_at" and plan.date_from == date.today().replace(day=1)
                results.append({"question": question, "passed": passed, "dataset": plan.dataset, "metric": plan.metric,
                                "group_by": plan.group_by, "filters": [item.model_dump() for item in plan.filters],
                                "row_count": response.row_count, "truncated": response.truncated, "unit": response.unit})
            except Exception as exc:
                results.append({"question": question, "passed": False, "error": type(exc).__name__, "message": str(exc)})
        for question in UNSUPPORTED_CASES:
            try:
                await run_text2sql(db, user, Text2SQLRequest(question=question), settings)
                results.append({"question": question, "passed": False, "error": "未拒绝不支持的指标"})
            except BusinessValidationError as exc:
                results.append({"question": question, "passed": "不支持" in str(exc), "result": "明确拒绝不支持的汇总"})
        print(json.dumps({"model": settings.llm_model, "case_count": len(results),
                          "passed_count": sum(item["passed"] for item in results), "cases": results}, ensure_ascii=False, default=str, indent=2))
        return 0 if all(item["passed"] for item in results) else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
