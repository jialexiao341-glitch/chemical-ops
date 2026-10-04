"""Rewrite legacy local-development business copy without rebuilding linked rows.

The database remains synthetic; see docs/开发环境业务记录.md. This script only
changes visible strings and requires a fresh, complete snapshot before apply.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from curated_record_copy import acceptance_copy, batch_no, business_no

NUMBERED = re.compile(r"^SCN26-(?:(\d+)-([A-Z]+\d*)|(ISS|OUT|STK|RET|TRF|TO|TI)-(\d+))$")
BACKGROUND = re.compile(
    r"([^，；]+)第\d+批：([^；]+)；本次申请([^，]+) (\d+)，按计划分批跟踪到货与验收"
)
EXACT = {
    "模拟供应商·东部试剂配送": "华东试剂配送中心",
    "模拟供应商·北方实验材料": "北方实验材料供应中心",
    "模拟常规供货能力": "常备规格可按订单分批交付",
    "仅供开发环境流程测试，非真实供应商": "按采购订单安排交期，随货提供批次资料",
    "仅供开发环境流程测试": "交期以订单确认为准，随货提供批次资料",
    "模拟询价记录": "供应商已按询价要求反馈报价及交期",
    "已发送询价文件，等待供应商按交期和规格回复": "供应商已按询价要求反馈报价及交期",
    "用于流程演示的模拟报价，无真实商业承诺": "报价按本次询价数量及约定交期填报，有效期内待采购确认",
    "模拟批次，不代表实物库存": "到货批次资料已关联收货记录",
    "模拟盘点，账实一致": "账面数量与本次盘点数量一致，无需调整",
    "仅为模拟发票数据，无真实税务凭证": "票面金额与订单及对账金额核对一致，附件待归档",
    "业务模拟样本，无真实税务票据": "票面金额与订单及对账金额核对一致，附件待归档",
    "仅为模拟付款数据，无真实资金划转": "付款登记金额与对账金额一致，银行回单待归档",
    "业务模拟样本，无真实银行付款": "付款登记金额与对账金额一致，银行回单待归档",
    "模拟结算；与订单及对账金额一致": "结算金额已与订单、发票及付款登记核对一致",
    "与对账、发票和付款金额一致的模拟结算": "结算金额已与订单、发票及付款登记核对一致",
    "已建立跟进任务，待取得供应商反馈；模拟记录。": "已联系供应商核实，待反馈补交时间及处理方案。",
}
PREFIX = {
    "项目甲": "分析方法确认组",
    "项目乙": "联合研发组",
    "项目丙": "稳定性研究组",
    "模拟业务场景：": "采购用途：",
    "模拟批次；": "到货批次按采购需求登记；",
    "模拟入库；": "验收后入库；",
    "模拟订单对账；": "按采购订单、到货记录及验收数量核对；",
    "园区合规承运商（模拟）": "园区危化品配送服务",
}
FIELDS = {
    "deliveries": ("delivery_no", "logistics_company", "tracking_no", "note"),
    "delivery_items": ("batch_no", "note"),
    "finance_invoices": ("invoice_no", "invoice_number", "note"),
    "finance_payments": ("payment_no", "transaction_ref", "note"),
    "finance_reconciliations": ("reconciliation_no", "note"),
    "finance_settlements": ("settlement_no", "note"),
    "inventory_batches": ("batch_no", "note"),
    "inventory_issue_requests": ("issue_no", "purpose"),
    "inventory_return_requests": ("return_no", "reason"),
    "inventory_stocktake_items": ("note",),
    "inventory_stocktake_requests": ("stocktake_no", "purpose"),
    "inventory_transactions": ("transaction_no", "note"),
    "inventory_transfer_requests": ("transfer_no", "purpose"),
    "operation_exceptions": ("exception_no",),
    "operation_task_comments": ("content",),
    "purchase_order_events": ("event_note",),
    "purchase_order_items": ("note",),
    "purchase_orders": ("po_no", "note"),
    "purchase_request_items": ("technical_requirements",),
    "purchase_requests": ("request_no", "purpose"),
    "quote_comparisons": ("comparison_no", "selection_reason"),
    "replenishment_requests": ("replenishment_no",),
    "rfq_items": ("technical_requirements",),
    "rfq_suppliers": ("note",),
    "rfqs": ("rfq_no", "delivery_requirements"),
    "supplier_products": ("capacity_note", "note"),
    "supplier_quote_items": ("note",),
    "supplier_quotes": ("quote_no", "note"),
    "suppliers": ("supplier_code", "supplier_name", "note"),
}


def rewrite(value: str) -> str:
    match = NUMBERED.fullmatch(value)
    if match:
        if match.group(1):
            number, kind = int(match.group(1)), match.group(2)
            kind = "QUO" if kind.startswith("Q") and kind != "QA" else kind
            suffix = match.group(2)[1:] if match.group(2).startswith("Q") and match.group(2) != "QA" else ""
        else:
            number, kind, suffix = int(match.group(4)), match.group(3), ""
        return business_no(number, kind) + (f"-{suffix}" if suffix else "")
    if value.startswith("SUP-SCN26-"):
        return "SUP-2026-" + value.rsplit("-", 1)[-1].zfill(4)
    if value.startswith("SIM-LOT-26-"):
        return batch_no(int(value.rsplit("-", 1)[-1]))
    if value.startswith("SIM-TRACK-"):
        return f"YQ202609{int(value.rsplit('-', 1)[-1]):04d}"
    if value.startswith("SIM-INVOICE-"):
        return f"FP202609{int(value.rsplit('-', 1)[-1]):06d}"
    if value.startswith("SIM-PAYMENT-"):
        return f"FIN202609{int(value.rsplit('-', 1)[-1]):06d}"
    if value == "SIM-BANK-26001":
        return "FIN202609900001"
    if value == "SIM-26001":
        return "FP202609900001"
    value = EXACT.get(value, value)
    for old, new in PREFIX.items():
        value = value.replace(old, new)
    return BACKGROUND.sub(lambda m: f"{m[1]}因{m[2]}，申请采购{m[3]} {m[4]} L；到货后核对批次及随货证明", value)


def preflight(path: Path) -> None:
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Only the local ChemicalOps development database may be changed")
    if not path.is_file() or path.stat().st_size < 1024:
        raise SystemExit("A complete local database snapshot is required")
    with gzip.open(path, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
    if header.get("database") != "chemicalops" or len(header.get("tables", [])) < 80:
        raise SystemExit("Snapshot does not match the current database")
    created = datetime.strptime(header["created_at"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > timedelta(hours=1):
        raise SystemExit("Snapshot must be less than one hour old")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    preflight(args.backup)
    counts = Counter()
    db = SessionLocal()
    try:
        for table, columns in FIELDS.items():
            keys = ("rfq_id", "supplier_id") if table == "rfq_suppliers" else ("id",)
            selected = ", ".join([f"`{key}`" for key in keys] + [f"`{column}`" for column in columns])
            rows = db.execute(text(f"SELECT {selected} FROM `{table}`")).mappings().all()
            for row in rows:
                changed = {col: rewrite(row[col]) for col in columns if isinstance(row[col], str) and rewrite(row[col]) != row[col]}
                if not changed:
                    continue
                counts[table] += 1
                if args.apply:
                    assignments = ", ".join(f"`{col}` = :{col}" for col in changed)
                    where = " AND ".join(f"`{key}` = :key_{key}" for key in keys)
                    db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE {where}"),
                               {**{f"key_{key}": row[key] for key in keys}, **changed})
        # The final volume-generated request was written with a fixed L suffix,
        # although its structured NaOH line uses the product's kg unit.
        unit_row = db.execute(text("""
            SELECT pr.id, pr.purpose, pri.id AS item_id, pri.technical_requirements,
                   pri.quantity, u.unit_name
            FROM purchase_requests pr
            JOIN purchase_request_items pri ON pri.request_id = pr.id
            JOIN md_units u ON u.id = pri.unit_id
            WHERE pr.request_no = 'PR-2026-0456' AND pri.line_no = 1
        """)).mappings().first()
        if unit_row:
            quantity = format(Decimal(str(unit_row["quantity"])).normalize(), "f")
            old_fragment = f"{quantity} L；"
            new_fragment = f"{quantity} {unit_row['unit_name']}；"
            for table, row_id, column in (
                ("purchase_requests", unit_row["id"], "purpose"),
                ("purchase_request_items", unit_row["item_id"], "technical_requirements"),
            ):
                value = unit_row[column]
                revised = value.replace(old_fragment, new_fragment, 1) if value and old_fragment in value else value
                if revised != value:
                    counts["purchase_request_unit_copy"] += 1
                    if args.apply:
                        db.execute(text(f"UPDATE `{table}` SET `{column}`=:value WHERE id=:id"),
                                   {"value": revised, "id": row_id})
        qa_rows = db.execute(text("""
            SELECT q.id, q.acceptance_no, q.result, q.certificate_complete, q.conclusion, q.test_result,
                   p.product_name, d.actual_arrival_date, di.planned_quantity, di.actual_quantity
            FROM quality_acceptances q JOIN deliveries d ON d.id = q.delivery_id
            JOIN delivery_items di ON di.delivery_id = d.id
            JOIN md_products p ON p.id = di.product_id
            WHERE q.acceptance_no LIKE 'SCN26-%' OR q.acceptance_no LIKE 'QA-2026-%'
        """)).mappings().all()
        for row in qa_rows:
            stage = "DOCUMENT" if not row["certificate_complete"] else "SHORT" if row["result"] == "PARTIAL" else "RECEIVED"
            case_no = int(row["acceptance_no"].split("-")[1]) if row["acceptance_no"].startswith("SCN26-") else int(row["acceptance_no"].rsplit("-", 1)[-1])
            result, conclusion = acceptance_copy(stage, row["product_name"], int(row["planned_quantity"]), int(row["actual_quantity"]), case_no)
            current_result = row["test_result"]
            if isinstance(current_result, str):
                current_result = json.loads(current_result)
            changed = row["conclusion"] != conclusion or current_result != result
            if changed:
                counts["quality_acceptances"] += 1
                if args.apply:
                    db.execute(text("UPDATE quality_acceptances SET conclusion=:conclusion, test_result=:result WHERE id=:id"),
                               {"id": row["id"], "conclusion": conclusion, "result": json.dumps(result, ensure_ascii=False)})
            if row["result"] == "PENDING" and row["certificate_complete"] and args.apply:
                raise RuntimeError(f"Unexpected pending QA without missing documents: {row['id']}")
        # Acceptance numbers are changed after the contextual rewrite query.
        for row in db.execute(text("SELECT id, acceptance_no FROM quality_acceptances WHERE acceptance_no LIKE 'SCN26-%'")).mappings():
            match = re.fullmatch(r"SCN26-(\d+)-QA", row["acceptance_no"])
            if match:
                counts["quality_acceptance_numbers"] += 1
                if args.apply:
                    db.execute(text("UPDATE quality_acceptances SET acceptance_no=:no WHERE id=:id"),
                               {"id": row["id"], "no": business_no(int(match[1]), "QA")})
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({"applied": args.apply, "updated_rows": dict(counts)}, ensure_ascii=False))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
