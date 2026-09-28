"""Populate hundreds of distinct, linked local-development business scenarios.

The scenario records are synthetic. They are not real orders, shipments,
physical inventory, supplier offers, invoices or bank transactions.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from extend_curated_dataset import (SessionLocal, PurchaseRequest, DeliveryItem,
    InventoryBatch, get_settings, main_seed, verify)


PRODUCTS = (
    ("PRD-ETHANOL-AR", 72), ("PRD-METHANOL-AR", 58),
    ("PRD-ACETONE-AR", 66), ("PRD-ACETIC-AR", 28),
    ("PRD-HCL-AR", 19), ("PRD-SULFURIC-AR", 26),
    ("PRD-NAOH-AR", 14), ("PRD-H2O2-AR", 32),
    ("PRD-TOLUENE-AR", 79), ("PRD-ETHYLACETATE-AR", 68),
    ("PRD-ACETONITRILE-AR", 116),
)
WORK_PACKAGES = (
    ("分析实验室", "色谱方法验证所需试剂补充"),
    ("质量控制室", "批次留样复核所需物料补充"),
    ("材料研发组", "材料相容性试验用量增加"),
    ("设备保障组", "年度检修窗口前备料"),
    ("环境监测组", "季度监测计划样品前处理备料"),
    ("水处理班组", "循环水系统维护物料补充"),
    ("生产一线", "中和工序安全库存复核后补库"),
    ("生产二线", "批次切换前原辅料储备"),
    ("工艺开发组", "小试转中试阶段用量调整"),
    ("安全管理组", "专用仓区安全库存调整"),
    ("仪器平台", "设备校准周期前试剂储备"),
    ("外协检测组", "委外样本交付周期配套物料"),
    ("样品制备室", "留样复测批次增加"),
    ("分析方法确认组", "客户方法确认阶段的试剂计划"),
    ("联合研发组", "联合研发阶段的耗材预测"),
    ("稳定性研究组", "稳定性试验计划调整"),
    ("仓储计划组", "季末消耗盘点后的补库"),
    ("采购计划组", "多部门需求汇总后的集中采购"),
    ("质量改进组", "偏差复核所需检验用料"),
    ("园区公用工程", "预防性维护窗口备料"),
)
PRODUCT_NAMES = {
    "PRD-ETHANOL-AR": "无水乙醇", "PRD-METHANOL-AR": "甲醇",
    "PRD-ACETONE-AR": "丙酮", "PRD-ACETIC-AR": "冰醋酸",
    "PRD-HCL-AR": "盐酸", "PRD-SULFURIC-AR": "硫酸",
    "PRD-NAOH-AR": "氢氧化钠", "PRD-H2O2-AR": "过氧化氢",
    "PRD-TOLUENE-AR": "甲苯", "PRD-ETHYLACETATE-AR": "乙酸乙酯",
    "PRD-ACETONITRILE-AR": "乙腈",
}


def scenario_cases():
    cases = []
    stages = ("SETTLED",) * 16 + ("RECEIVED",) * 3 + (
        "SHORT", "DOCUMENT", "TRANSIT", "ORDERED", "RFQ", "DRAFT")
    for index, number in enumerate(range(27, 327)):
        product_code, base_price = PRODUCTS[(index * 7 + index // 11) % len(PRODUCTS)]
        team, reason = WORK_PACKAGES[index % len(WORK_PACKAGES)]
        quantity = 24 + (index * 37 + index // 7 * 11) % 177
        unit_price = base_price + (index % 9) - 4
        background = f"{team}因{reason}，申请采购{PRODUCT_NAMES[product_code]} {quantity} L；到货后核对批次及随货证明"
        cases.append((number, product_code, quantity, unit_price, background,
            stages[index % len(stages)], index % 3))
    return tuple(cases)


def normalize_expiry_dates(db):
    """Keep sample batch shelf life plausible, including previously seeded cases."""
    today = date.today()
    items = list(db.scalars(select(DeliveryItem).where(DeliveryItem.batch_no.like("B2609____"))).all())
    batches = {batch.source_delivery_id: batch for batch in db.scalars(
        select(InventoryBatch).where(InventoryBatch.batch_no.like("B2609____"))).all()}
    changed = 0
    for item in items:
        number = int(item.batch_no[5:])
        expiry = today + timedelta(days=240 + number % 180)
        if item.expiry_date != expiry:
            item.expiry_date = expiry
            changed += 1
        batch = batches.get(item.delivery_id)
        if batch and batch.expiry_date != expiry:
            batch.expiry_date = expiry
            changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True, help="A fresh database snapshot")
    parser.add_argument("--validate-transaction", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Only the local ChemicalOps development database may be changed")
    if not args.backup.is_file() or args.backup.stat().st_size < 1024:
        raise SystemExit("A recent nonempty backup is required")
    with gzip.open(args.backup, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
    if header.get("database") != "chemicalops":
        raise SystemExit("Backup belongs to a different database")
    db = SessionLocal()
    try:
        if db.scalar(select(PurchaseRequest.id).where(PurchaseRequest.request_no.in_(("SCN26-27-PR", "PR-2026-0027")))):
            changed = normalize_expiry_dates(db) if args.apply else 0
            if args.apply:
                verify(db)
                db.commit()
            print(json.dumps({"already_applied": True, "expiry_dates_corrected": changed}))
            return
        cases = scenario_cases()
        if not (args.apply or args.validate_transaction):
            print(json.dumps({"dry_run": True, "new_cases": len(cases), "stage_counts":
                {status: sum(item[5] == status for item in cases) for status in set(item[5] for item in cases)}}, ensure_ascii=False))
            return
        counts = main_seed(db, cases, add_master=False)
        normalize_expiry_dates(db)
        result = verify(db)
        if args.validate_transaction:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({"rolled_back": args.validate_transaction, "created": counts,
            "verified": result}, ensure_ascii=False, default=dict))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
