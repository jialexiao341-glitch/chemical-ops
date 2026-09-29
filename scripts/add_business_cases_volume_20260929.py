"""Add a larger, linked set of constructed business cases to the local development database."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from add_business_cases_20260929 import check_backup
from expand_curated_dataset import PRODUCTS, PRODUCT_NAMES
from extend_curated_dataset import PurchaseRequest, SessionLocal, get_settings, main_seed, verify
from app.modules.inventory.model import Warehouse, WarehouseLocation
from app.modules.products.model import Product
from app.modules.suppliers.model import Supplier
from app.modules.suppliers.product_model import SupplierProduct


CONTEXTS = (
    "质量控制室复核月度试剂消耗，补充",
    "研发中心调整下一批实验用料计划，补充",
    "工艺组安排分批验证，申请",
    "仓储计划组复核安全库存，补充",
    "分析实验室根据方法确认排期采购",
    "原料检验室安排留样复测，补充",
    "设备保障组为检修窗口提前准备",
    "生产一线为批次切换储备",
    "环境监测组按季度采样计划采购",
    "园区公用工程按维护计划补充",
    "联合研发组调整小试用量，采购",
    "采购计划组汇总跨部门需求，补充",
)
STAGES = (
    ("SETTLED",) * 30 + ("RECEIVED",) * 10 + ("SHORT",) * 30
    + ("DOCUMENT",) * 10 + ("TRANSIT",) * 10 + ("ORDERED",) * 10
    + ("RFQ",) * 8 + ("SUBMITTED",) * 6 + ("DRAFT",) * 6
)
REGIONS = ("华东", "华南", "华北", "华中", "西南", "西北")
SPECIALTIES = ("实验材料", "工业试剂", "分析试剂", "化学品配送", "工艺材料")


def product_code(index: int) -> str:
    return f"{PRODUCTS[index % len(PRODUCTS)][0]}-P{index + 1:02d}"


def add_master_data(db) -> Counter[str]:
    counts: Counter[str] = Counter()
    base_products = {item.product_code: item for item in db.scalars(select(Product)).all()}
    warehouses = list(db.scalars(select(Warehouse).order_by(Warehouse.id)).all())
    if len(warehouses) < 4 or any(code not in base_products for code, _ in PRODUCTS):
        raise RuntimeError("Required source products or warehouses are missing")

    suppliers = []
    for index in range(30):
        region = REGIONS[index % len(REGIONS)]
        specialty = SPECIALTIES[index // len(REGIONS)]
        supplier = Supplier(
            supplier_code=f"SUP-2026-{1001 + index}",
            supplier_name=f"{region}{specialty}供应中心{index + 1:02d}",
            country_code="CN", region=region,
            business_scope=f"{specialty}采购与配送",
            payment_terms="验收后按合同约定结算",
            default_lead_days=4 + index % 9,
            status="ACTIVE",
        )
        db.add(supplier)
        suppliers.append(supplier)
    db.flush()
    counts["suppliers"] = len(suppliers)

    for index in range(30):
        base_code, _ = PRODUCTS[index % len(PRODUCTS)]
        base = base_products[base_code]
        package = ("5L/桶", "10L/桶", "20L/桶")[index % 3]
        product = Product(
            product_code=product_code(index), product_name=base.product_name,
            chemical_id=base.chemical_id, category_id=base.category_id,
            model=f"{base.model or '常规'}-{package}", packaging_spec=package,
            unit_id=base.unit_id, parameter_json={"certificate_required": True},
            version_no=1, status="ACTIVE",
        )
        db.add(product)
        db.flush()
        counts["md_products"] += 1
        for option in range(3):
            supplier = suppliers[(index + option * 10) % len(suppliers)]
            db.add(SupplierProduct(
                supplier_id=supplier.id, product_id=product.id,
                supplier_model=f"{base.model or '常规'}-{5 * (2 ** (index % 3))}L",
                moq_quantity=10 + option * 5, moq_unit_id=product.unit_id,
                standard_lead_days=supplier.default_lead_days,
                capacity_note="分批交付需按订单确认", status="ACTIVE",
            ))
            counts["supplier_products"] += 1

    for warehouse in warehouses[:4]:
        for row in range(2, 8):
            db.add(WarehouseLocation(
                warehouse_id=warehouse.id, location_code=f"B-{row:02d}-01",
                location_name=f"B排{row:02d}列01位", status="ACTIVE",
            ))
            counts["warehouse_locations"] += 1
    db.flush()
    return counts


def cases() -> tuple[tuple[int, str, int, int, str, str, int], ...]:
    result = []
    for index, number in enumerate(range(337, 457)):
        product_index = (index * 7 + index // 9) % 30
        base_code, base_price = PRODUCTS[product_index % len(PRODUCTS)]
        code = product_code(product_index)
        quantity = 24 + (index * 43 + index // 11 * 7) % 157
        unit_price = base_price + index % 9 - 4
        background = (
            f"{CONTEXTS[index % len(CONTEXTS)]}{PRODUCT_NAMES[base_code]} {quantity} L；"
            "按产品规格核对包装、批号和随货资料"
        )
        result.append((number, code, quantity, unit_price, background, STAGES[index % len(STAGES)], index % 3))
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-transaction", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Only the local ChemicalOps development database may be changed")
    if args.apply or args.validate_transaction:
        if args.backup is None:
            raise SystemExit("A recent --backup is required")
        check_backup(args.backup, settings.mysql_database)

    batch = cases()
    numbers = {f"PR-2026-{number:04d}" for number, *_ in batch}
    with SessionLocal() as db:
        found = set(db.scalars(select(PurchaseRequest.request_no).where(PurchaseRequest.request_no.in_(numbers))).all())
        if found == numbers:
            print(json.dumps({"already_applied": True, "case_count": len(batch)}))
            return
        if found:
            raise SystemExit(f"Partial import detected: {len(found)} requests already exist")
        if not (args.apply or args.validate_transaction):
            print(json.dumps({"dry_run": True, "case_count": len(batch), "suppliers": 30, "products": 30, "locations": 24, "first_request": min(numbers), "last_request": max(numbers)}))
            return
        try:
            counts = add_master_data(db)
            counts.update(main_seed(db, cases=batch, add_master=False))
            verify(db)
            if args.validate_transaction:
                db.rollback()
            else:
                db.commit()
        except Exception:
            db.rollback()
            raise
    print(json.dumps({"rolled_back": args.validate_transaction, "created": counts}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
