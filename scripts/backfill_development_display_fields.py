"""Audit and complete missing display fields in the synthetic development corpus.

Only fills empty values. Financial snapshots, lifecycle events, safety limits,
credentials and chemical hazard classifications are never synthesized.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings
from app.core.db import engine


def plan(db):
    updates = []
    def fill(table, row, values):
        missing = {key: value for key, value in values.items()
                   if row.get(key) in (None, "") and value not in (None, "")}
        if missing:
            updates.append((table, row["id"], missing))
            row.update(missing)

    products = [dict(row) for row in db.execute(text("SELECT * FROM md_products")).mappings()]
    by_product = {row["id"]: row for row in products}
    # Copy already-defined purity only within the same chemical and reagent grade.
    purities = {}
    for row in products:
        if row["purity_value"] is not None:
            key = (row["chemical_id"], (row["model"] or "").split("-")[0])
            purities.setdefault(key, set()).add(row["purity_value"])
    for row in products:
        key = (row["chemical_id"], (row["model"] or "").split("-")[0])
        values = purities.get(key, set())
        if len(values) == 1:
            fill("md_products", row, {"purity_value": next(iter(values))})
    for row in db.execute(text("SELECT * FROM supplier_products")).mappings():
        row = dict(row)
        product = by_product.get(row["product_id"], {})
        fill("supplier_products", row, {"supplied_purity": product.get("purity_value")})

    for row in db.execute(text("SELECT * FROM suppliers")).mappings():
        row = dict(row)
        fill("suppliers", row, {
            "address": f"演示地址：{row['region'] or '本地'}试剂配送区",
            "business_scope": "开发演示：实验室试剂及配套耗材配送",
            "cooperation_level": "B",
            "payment_terms": "开发演示：验收对账后30天付款",
        })
    for row in db.execute(text("SELECT * FROM warehouses")).mappings():
        row = dict(row)
        fill("warehouses", row, {"address": f"演示地址：研发园区 {row['warehouse_code']} 仓储区"})

    # These six invoice samples explicitly omit dates in the original generator.
    invoice_day = date(2026, 9, 30)
    order_day = invoice_day - timedelta(days=7)
    arrival_day = invoice_day - timedelta(days=1)
    for row in db.execute(text("SELECT * FROM purchase_orders WHERE po_no LIKE 'PO-SIMINV-%'")).mappings():
        row = dict(row)
        fill("purchase_orders", row, {"order_date": order_day,
             "expected_arrival_date": arrival_day, "delivery_address": "开发演示：研发园区收货区"})
    orders = {row["id"]: dict(row) for row in db.execute(text("SELECT * FROM purchase_orders")).mappings()}
    for row in db.execute(text("SELECT * FROM purchase_order_items")).mappings():
        row = dict(row)
        order = orders.get(row["po_id"], {})
        product = by_product.get(row["product_id"], {})
        expected = order.get("expected_arrival_date")
        if (order.get("po_no") or "").startswith("PO-SIMINV-"):
            expected = expected or arrival_day
        fill("purchase_order_items", row, {"supplier_model_snapshot": product.get("model"),
             "planned_arrival_date": expected})
    for row in db.execute(text("SELECT * FROM deliveries WHERE delivery_no LIKE 'DLV-SIMINV-%'")).mappings():
        row = dict(row)
        fill("deliveries", row, {"shipment_date": arrival_day - timedelta(days=1),
             "expected_arrival_date": arrival_day, "actual_arrival_date": arrival_day,
             "logistics_company": "开发演示物流", "tracking_no": f"DEMO-{row['delivery_no']}"})
    for row in db.execute(text("SELECT * FROM delivery_items")).mappings():
        row = dict(row)
        product = by_product.get(row["product_id"], {})
        fill("delivery_items", row, {"package_spec": product.get("packaging_spec")})
    return updates


def audit(db):
    result = []
    inspector = inspect(db)
    for table in inspector.get_table_names():
        if table.startswith(("sys_", "ai_", "schema_", "chemical_")):
            continue
        columns = [column for column in inspector.get_columns(table) if column["nullable"]]
        if not columns:
            continue
        expressions = [f"SUM(`{column['name']}` IS NULL) AS `{column['name']}`" for column in columns]
        row = db.execute(text(f"SELECT COUNT(*) AS total,{','.join(expressions)} FROM `{table}`")).mappings().one()
        missing = {key: int(value) for key, value in row.items() if key != "total" and value}
        if missing:
            result.append({"table": table, "total": row["total"], "null_fields": missing})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Only the local ChemicalOps development database is supported")
    if args.apply:
        if not args.backup or not args.backup.is_file():
            raise SystemExit("A complete development snapshot is required before apply")
        with gzip.open(args.backup, "rt", encoding="utf-8") as source:
            header = json.loads(next(source))
        if header.get("database") != get_settings().mysql_database:
            raise SystemExit("Snapshot database does not match")
    with engine.begin() as db:
        before = audit(db)
        updates = plan(db)
        counts = Counter()
        fields = Counter()
        for table, row_id, values in updates:
            counts[table] += 1
            fields.update(f"{table}.{key}" for key in values)
            if args.apply:
                assignments = ",".join(f"`{key}`=:{key}" for key in values)
                db.execute(text(f"UPDATE `{table}` SET {assignments} WHERE id=:record_id"),
                           {**values, "record_id": row_id})
        remaining_plan = plan(db) if args.apply else updates
        if args.apply and remaining_plan:
            raise RuntimeError("Backfill did not converge; transaction rolled back")
        report = {"applied": args.apply, "rows_by_table": dict(counts),
                  "fields_filled": dict(fields), "before": before,
                  "after": audit(db) if args.apply else None,
                  "pending_backfill_rows": len(remaining_plan)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ["applied", "rows_by_table", "fields_filled", "pending_backfill_rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
