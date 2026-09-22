"""获取公开化学品数据，并装载一套可替换的开发数据。

数据策略：
1. 化学品身份字段通过 PubChem PUG REST 真实查询；
2. 供应商、产品规格、采购、到货、库存和异常记录使用固定输入生成；
3. 统一清洗名称、CAS、日期、金额、数量和状态后再入库；
4. 所有业务编号可重复执行，已存在记录不会被覆盖。

示例：
    python scripts/load_development_dataset.py --dry-run
    python scripts/load_development_dataset.py --public-limit 11
    python scripts/load_development_dataset.py --skip-public
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.modules.chemicals.model import Chemical  # noqa: E402
from app.modules.deliveries.model import Delivery, DeliveryItem  # noqa: E402
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, Warehouse, WarehouseLocation  # noqa: E402
from app.modules.notifications.model import Notification  # noqa: E402
from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment  # noqa: E402
from app.modules.products.category_model import ProductCategory  # noqa: E402
from app.modules.products.model import Product  # noqa: E402
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem  # noqa: E402
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestItem, Unit  # noqa: E402
from app.modules.quality_acceptances.model import QualityAcceptance  # noqa: E402
from app.modules.rfqs.model import RFQ, RFQItem, RFQSupplier, QuoteComparison, QuoteComparisonItem, SupplierQuote, SupplierQuoteItem  # noqa: E402
from app.modules.suppliers.model import Supplier  # noqa: E402
from app.modules.suppliers.product_model import SupplierProduct  # noqa: E402
from app.modules.system.model import Department, User  # noqa: E402
from import_pubchem_chemicals import DEFAULT_CHEMICALS, build_row, fetch_properties, write_outputs  # noqa: E402


T = TypeVar("T")
TODAY = date.today()


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    result = re.sub(r"\s+", " ", str(value)).strip()
    return result or None


def clean_code(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().upper())
    return re.sub(r"-+", "-", result).strip("-")


def clean_decimal(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def ensure(db: Session, model: type[T], where: dict[str, Any], values: dict[str, Any], counts: Counter[str]) -> T:
    obj = db.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where, **values)
        db.add(obj)
        db.flush()
        counts[model.__tablename__] += 1  # type: ignore[attr-defined]
    return obj


def fetch_public_rows(limit: int, delay: float, run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    raw_payloads: dict[str, Any] = {}
    failures: list[str] = []
    for chemical_name, english_name, cas_no in DEFAULT_CHEMICALS[:limit]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                properties = fetch_properties(cas_no, delay)
                raw_payloads[cas_no] = properties
                rows.append(build_row(chemical_name, english_name, cas_no, properties))
                print(f"public_downloaded cas={cas_no} name={chemical_name}")
                break
            except (RuntimeError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 + attempt)
        else:
            failures.append(f"{cas_no}: {last_error}")
            print(f"public_failed cas={cas_no} reason={last_error}")
    write_outputs(
        run_dir,
        raw_payloads,
        rows,
        {"requested": limit, "downloaded": len(rows), "failed": len(failures), "created": 0, "skipped_existing": 0},
    )
    return rows, failures


def upsert_public_chemicals(db: Session, rows: list[dict[str, Any]], counts: Counter[str]) -> dict[str, Chemical]:
    chemical_map: dict[str, Chemical] = {}
    for row in rows:
        cas_no = clean_text(row["cas_no"])
        if not cas_no:
            continue
        chemical = ensure(
            db,
            Chemical,
            {"cas_no": cas_no},
            {
                "chemical_name": clean_text(row["chemical_name"]) or cas_no,
                "english_name": clean_text(row.get("english_name")),
                "alias_text": clean_text(row.get("alias_text")),
                "chemical_formula": clean_text(row.get("chemical_formula")),
                "molecular_weight": row.get("molecular_weight"),
                "hazard_class": row.get("hazard_class"),
                "source_text": row.get("source_text"),
                "status": "ACTIVE",
            },
            counts,
        )
        chemical_map[cas_no] = chemical
    return chemical_map


def load_units(db: Session, counts: Counter[str]) -> dict[str, Unit]:
    definitions = {
        "KG": ("千克", "MASS"),
        "G": ("克", "MASS"),
        "L": ("升", "VOLUME"),
        "ML": ("毫升", "VOLUME"),
    }
    return {code: ensure(db, Unit, {"unit_code": code}, {"unit_name": name, "dimension": dimension, "status": "ACTIVE"}, counts) for code, (name, dimension) in definitions.items()}


def load_organization(db: Session, counts: Counter[str]) -> tuple[dict[str, Department], dict[str, User]]:
    departments: dict[str, Department] = {}
    for code, name in (("PROCUREMENT", "采购部"), ("QUALITY", "质量部"), ("WAREHOUSE", "仓储部")):
        departments[code] = ensure(db, Department, {"department_code": code}, {"department_name": name, "status": "ACTIVE"}, counts)

    users: dict[str, User] = {}
    definitions = (
        ("buyer", "采购员", "buyer@chemicalops.local", "PROCUREMENT"),
        ("quality", "质量专员", "quality@chemicalops.local", "QUALITY"),
        ("warehouse", "仓库管理员", "warehouse@chemicalops.local", "WAREHOUSE"),
    )
    for username, display_name, email, department_code in definitions:
        users[username] = ensure(
            db,
            User,
            {"username": username},
            {
                "password_hash": hash_password("ChemicalOps@123"),
                "display_name": display_name,
                "department_id": departments[department_code].id,
                "email": email,
                "status": "ACTIVE",
            },
            counts,
        )
    for department_code, username in (("PROCUREMENT", "buyer"), ("QUALITY", "quality"), ("WAREHOUSE", "warehouse")):
        if departments[department_code].manager_id is None:
            departments[department_code].manager_id = users[username].id
    return departments, users


def load_master_data(db: Session, chemical_map: dict[str, Chemical], units: dict[str, Unit], counts: Counter[str]) -> tuple[dict[str, Product], dict[str, Supplier], dict[tuple[str, str], SupplierProduct], Warehouse, WarehouseLocation]:
    categories: dict[str, ProductCategory] = {}
    for code, name in (("SOLVENT", "有机溶剂"), ("ACID_BASE", "酸碱试剂"), ("OXIDIZER", "氧化剂"), ("GENERAL", "通用试剂")):
        categories[code] = ensure(db, ProductCategory, {"category_code": code}, {"category_name": name, "status": "ACTIVE"}, counts)

    supplier_specs = (
        ("SUP-26001", "华辰精细化工", "华东", "A", 4),
        ("SUP-26002", "瑞科试剂供应链", "华南", "A", 5),
        ("SUP-26003", "安研化学材料", "华北", "B", 7),
        ("SUP-26004", "远洋实验室用品", "华中", "B", 6),
    )
    suppliers: dict[str, Supplier] = {}
    for code, name, region, level, lead_days in supplier_specs:
        suppliers[code] = ensure(
            db,
            Supplier,
            {"supplier_code": clean_code(code)},
            {"supplier_name": clean_text(name) or name, "country_code": "CN", "region": region, "cooperation_level": level, "default_lead_days": lead_days, "status": "ACTIVE"},
            counts,
        )

    product_specs = (
        ("PRD-ETHANOL-AR", "无水乙醇", "64-17-5", "AR", 99.5, "25L/桶", "L", "SOLVENT", ("SUP-26001", "SUP-26002", "SUP-26004")),
        ("PRD-METHANOL-AR", "甲醇", "67-56-1", "AR", 99.5, "25L/桶", "L", "SOLVENT", ("SUP-26001", "SUP-26003")),
        ("PRD-ACETONE-AR", "丙酮", "67-64-1", "AR", 99.5, "20L/桶", "L", "SOLVENT", ("SUP-26001", "SUP-26002", "SUP-26004")),
        ("PRD-ACETIC-AR", "冰醋酸", "64-19-7", "AR", 99.5, "25kg/桶", "KG", "GENERAL", ("SUP-26002", "SUP-26003")),
        ("PRD-HCL-AR", "盐酸", "7647-01-0", "AR", 36.0, "25kg/桶", "KG", "ACID_BASE", ("SUP-26001", "SUP-26003", "SUP-26004")),
        ("PRD-SULFURIC-AR", "硫酸", "7664-93-9", "AR", 98.0, "25kg/桶", "KG", "ACID_BASE", ("SUP-26001", "SUP-26003")),
        ("PRD-NAOH-AR", "氢氧化钠", "1310-73-2", "AR", 96.0, "25kg/袋", "KG", "ACID_BASE", ("SUP-26001", "SUP-26002", "SUP-26003", "SUP-26004")),
        ("PRD-H2O2-AR", "过氧化氢", "7722-84-1", "AR", 30.0, "25kg/桶", "KG", "OXIDIZER", ("SUP-26003", "SUP-26004")),
    )
    products: dict[str, Product] = {}
    supplier_products: dict[tuple[str, str], SupplierProduct] = {}
    for code, name, cas_no, model, purity, packaging, unit_code, category_code, supplier_codes in product_specs:
        chemical = chemical_map.get(cas_no)
        if chemical is None:
            raise RuntimeError(f"缺少公开化学品数据，无法创建产品：{cas_no}")
        product = ensure(
            db,
            Product,
            {"product_code": clean_code(code)},
            {"product_name": name, "chemical_id": chemical.id, "category_id": categories[category_code].id, "model": model, "purity_value": clean_decimal(purity), "purity_unit": "%", "packaging_spec": packaging, "unit_id": units[unit_code].id, "parameter_json": {"storage_temperature": "15-25°C", "certificate_required": True}, "version_no": 1, "status": "ACTIVE"},
            counts,
        )
        products[code] = product
        for index, supplier_code in enumerate(supplier_codes):
            supplier = suppliers[supplier_code]
            supplier_products[(supplier_code, code)] = ensure(
                db,
                SupplierProduct,
                {"supplier_id": supplier.id, "product_id": product.id},
                {"supplier_model": f"{model}-{index + 1:02d}", "supplied_purity": clean_decimal(purity), "moq_quantity": clean_decimal(25 if unit_code == "KG" else 20), "moq_unit_id": units[unit_code].id, "standard_lead_days": supplier.default_lead_days, "capacity_note": "常规库存" if index == 0 else "按订单排产", "status": "ACTIVE"},
                counts,
            )

    warehouse = ensure(db, Warehouse, {"warehouse_code": "WH-26001"}, {"warehouse_name": "化学品综合仓", "region": "华东", "address": "研发园区 A 区", "status": "ACTIVE"}, counts)
    location = ensure(db, WarehouseLocation, {"warehouse_id": warehouse.id, "location_code": "A-01-01"}, {"location_name": "A 区 01 排 01 位", "status": "ACTIVE"}, counts)
    return products, suppliers, supplier_products, warehouse, location


def load_procurement_chain(db: Session, products: dict[str, Product], suppliers: dict[str, Supplier], supplier_products: dict[tuple[str, str], SupplierProduct], units: dict[str, Unit], departments: dict[str, Department], users: dict[str, User], warehouse: Warehouse, location: WarehouseLocation, counts: Counter[str]) -> None:
    request_specs = (
        ("PR-26001", "研发实验室常用溶剂补充", "HIGH", 4200, 12, (("PRD-ETHANOL-AR", 50, "L"), ("PRD-ACETONE-AR", 40, "L"))),
        ("PR-26002", "酸碱试剂库存补充", "NORMAL", 3600, 20, (("PRD-HCL-AR", 50, "KG"), ("PRD-NAOH-AR", 75, "KG"))),
        ("PR-26003", "氧化剂安全库存建立", "URGENT", 2800, 28, (("PRD-H2O2-AR", 50, "KG"),)),
    )
    requests: list[tuple[PurchaseRequest, list[PurchaseRequestItem]]] = []
    for index, (request_no, purpose, priority, budget, day_offset, item_specs) in enumerate(request_specs):
        request = ensure(db, PurchaseRequest, {"request_no": request_no}, {"applicant_id": users["buyer"].id, "department_id": departments["PROCUREMENT"].id, "purpose": purpose, "priority": priority, "budget_amount": clean_decimal(budget), "currency_code": "CNY", "expected_date": TODAY + timedelta(days=day_offset), "status": "APPROVED" if index < 2 else "SUBMITTED", "submitted_at": datetime.now(timezone.utc) - timedelta(days=5 - index), "approved_at": datetime.now(timezone.utc) - timedelta(days=3 - index) if index < 2 else None}, counts)
        items: list[PurchaseRequestItem] = []
        for line_no, (product_code, quantity, unit_code) in enumerate(item_specs, start=1):
            product = products[product_code]
            items.append(ensure(db, PurchaseRequestItem, {"request_id": request.id, "line_no": line_no}, {"product_id": product.id, "requested_name": product.product_name, "technical_requirements": "符合采购规格并提供 COA", "quantity": clean_decimal(quantity), "unit_id": units[unit_code].id, "budget_price": clean_decimal(80 if unit_code == "L" else 18), "expected_date": TODAY + timedelta(days=12 + index * 4), "fulfilled_quantity": clean_decimal(quantity if index == 0 else 0), "status": "FULFILLED" if index == 0 else "OPEN"}, counts))
        requests.append((request, items))

    rfq_specs = (("RFQ-26001", requests[0], ("SUP-26001", "SUP-26002", "SUP-26004")), ("RFQ-26002", requests[1], ("SUP-26001", "SUP-26003", "SUP-26004")))
    quote_context: list[tuple[RFQ, dict[str, SupplierQuote], dict[tuple[str, str], SupplierQuoteItem], QuoteComparison]] = []
    for rfq_no, (request, request_items), invited_codes in rfq_specs:
        rfq = ensure(db, RFQ, {"rfq_no": rfq_no}, {"source_request_id": request.id, "requester_id": users["buyer"].id, "quote_deadline": datetime.now(timezone.utc) + timedelta(days=4), "requested_delivery_date": TODAY + timedelta(days=18), "delivery_requirements": "送货至主仓，随货提供 COA", "status": "SENT", "sent_at": datetime.now(timezone.utc) - timedelta(days=2)}, counts)
        rfq_items: list[RFQItem] = []
        for request_item in request_items:
            rfq_items.append(ensure(db, RFQItem, {"rfq_id": rfq.id, "line_no": request_item.line_no}, {"source_request_item_id": request_item.id, "product_id": request_item.product_id, "requested_name": request_item.requested_name, "specification": "分析纯", "quantity": request_item.quantity, "unit_id": request_item.unit_id, "required_delivery_date": request_item.expected_date, "technical_requirements": request_item.technical_requirements}, counts))
        quotes: dict[str, SupplierQuote] = {}
        quote_items: dict[tuple[str, str], SupplierQuoteItem] = {}
        for supplier_index, supplier_code in enumerate(invited_codes):
            supplier = suppliers[supplier_code]
            ensure(db, RFQSupplier, {"rfq_id": rfq.id, "supplier_id": supplier.id}, {"response_status": "QUOTED", "response_at": datetime.now(timezone.utc) - timedelta(days=1), "invitation_channel": "EMAIL"}, counts)
            quote = ensure(db, SupplierQuote, {"quote_no": f"Q-{rfq_no[-5:]}-{supplier_index + 1:02d}"}, {"rfq_id": rfq.id, "supplier_id": supplier.id, "quote_version": 1, "quote_date": TODAY - timedelta(days=1), "valid_until": TODAY + timedelta(days=14), "currency_code": "CNY", "status": "SUBMITTED", "received_by": users["buyer"].id}, counts)
            quotes[supplier_code] = quote
            for rfq_item in rfq_items:
                product_code = next(code for code, product in products.items() if product.id == rfq_item.product_id)
                unit_code = next(code for code, unit in units.items() if unit.id == rfq_item.unit_id)
                base_price = Decimal("72") if unit_code == "L" else Decimal("16")
                unit_price = base_price + Decimal(str(supplier_index * 2 + (1 if product_code.endswith("H2O2-AR") else 0)))
                quote_items[(supplier_code, product_code)] = ensure(db, SupplierQuoteItem, {"quote_id": quote.id, "rfq_item_id": rfq_item.id}, {"supplier_product_id": supplier_products[(supplier_code, product_code)].id, "supplier_model": supplier_products[(supplier_code, product_code)].supplier_model, "quoted_quantity": rfq_item.quantity, "unit_id": rfq_item.unit_id, "unit_price": unit_price, "tax_rate": clean_decimal(13), "moq_quantity": clean_decimal(25), "moq_unit_id": rfq_item.unit_id, "lead_days": suppliers[supplier_code].default_lead_days, "payment_terms": "月结 30 天"}, counts)
        selected_supplier = invited_codes[0]
        comparison = ensure(db, QuoteComparison, {"comparison_no": f"QC-{rfq_no[-5:]}"}, {"rfq_id": rfq.id, "created_by": users["buyer"].id, "selected_quote_id": quotes[selected_supplier].id, "conclusion": "综合价格、交期和历史履约表现后选择报价。", "selection_reason": "满足交期且综合成本最低。", "status": "CONFIRMED", "confirmed_by": users["buyer"].id, "confirmed_at": datetime.now(timezone.utc) - timedelta(hours=12)}, counts)
        for rfq_item in rfq_items:
            product_code = next(code for code, product in products.items() if product.id == rfq_item.product_id)
            for rank, supplier_code in enumerate(invited_codes, start=1):
                quote_item = quote_items[(supplier_code, product_code)]
                total_amount = quote_item.unit_price * quote_item.quoted_quantity
                ensure(db, QuoteComparisonItem, {"comparison_id": comparison.id, "quote_id": quote_item.quote_id, "rfq_item_id": rfq_item.id}, {"supplier_id": suppliers[supplier_code].id, "quoted_unit_price": quote_item.unit_price, "total_amount": total_amount, "moq_quantity": quote_item.moq_quantity, "lead_days": quote_item.lead_days, "payment_terms": quote_item.payment_terms, "historical_score": clean_decimal(92 - rank * 4), "composite_score": clean_decimal(96 - rank * 3), "rank_no": rank, "selection_flag": 1 if rank == 1 else 0}, counts)
        quote_context.append((rfq, quotes, quote_items, comparison))

    orders: list[tuple[PurchaseOrder, PurchaseOrderItem, str]] = []
    order_specs = (("PO-26001", quote_context[0], "SUP-26001", "PRD-ETHANOL-AR", 50, "L", "RECEIVED"), ("PO-26002", quote_context[0], "SUP-26001", "PRD-ACETONE-AR", 40, "L", "PARTIAL"), ("PO-26003", quote_context[1], "SUP-26003", "PRD-HCL-AR", 50, "KG", "IN_TRANSIT"))
    for po_no, (rfq, quotes, quote_items, comparison), supplier_code, product_code, quantity, unit_code, delivery_status in order_specs:
        product = products[product_code]
        quote = quotes[supplier_code]
        quote_item = quote_items[(supplier_code, product_code)]
        order = ensure(db, PurchaseOrder, {"po_no": po_no}, {"supplier_id": suppliers[supplier_code].id, "source_comparison_id": comparison.id, "source_quote_id": quote.id, "source_request_id": rfq.source_request_id, "department_id": departments["PROCUREMENT"].id, "buyer_id": users["buyer"].id, "order_amount": quote_item.unit_price * clean_decimal(quantity), "currency_code": "CNY", "delivery_address": "研发园区 A 区主仓", "order_date": TODAY - timedelta(days=10), "expected_arrival_date": TODAY - timedelta(days=3) if delivery_status != "IN_TRANSIT" else TODAY - timedelta(days=1), "status": ("COMPLETED" if delivery_status == "RECEIVED" else "PARTIAL" if delivery_status == "PARTIAL" else "ORDERED"), "supplier_confirmed_at": datetime.now(timezone.utc) - timedelta(days=8), "approved_at": datetime.now(timezone.utc) - timedelta(days=9)}, counts)
        order_item = ensure(db, PurchaseOrderItem, {"po_id": order.id, "line_no": 1}, {"product_id": product.id, "supplier_product_id": supplier_products[(supplier_code, product_code)].id, "source_quote_item_id": quote_item.id, "product_name_snapshot": product.product_name, "supplier_model_snapshot": quote_item.supplier_model, "order_quantity": clean_decimal(quantity), "unit_id": units[unit_code].id, "unit_price": quote_item.unit_price, "tax_rate": clean_decimal(13), "planned_arrival_date": order.expected_arrival_date, "received_quantity": clean_decimal(quantity if delivery_status == "RECEIVED" else quantity * Decimal("0.8") if delivery_status == "PARTIAL" else 0), "status": "COMPLETED" if delivery_status == "RECEIVED" else "OPEN"}, counts)
        ensure(db, PurchaseOrderEvent, {"po_id": order.id, "event_type": "ORDERED"}, {"event_time": datetime.now(timezone.utc) - timedelta(days=9), "operator_id": users["buyer"].id, "from_status": "APPROVED", "to_status": "ORDERED", "event_note": "订单已正式下单"}, counts)
        orders.append((order, order_item, delivery_status))

    delivery_specs = (("DLV-26001", orders[0], "FULL", 0), ("DLV-26002", orders[1], "SHORT", 8), ("DLV-26003", orders[2], "OVERDUE", 0))
    deliveries: list[tuple[Delivery, DeliveryItem, str]] = []
    for delivery_no, (order, order_item, delivery_status), scenario, short_quantity in delivery_specs:
        actual_quantity = order_item.order_quantity if scenario == "FULL" else order_item.order_quantity - clean_decimal(short_quantity) if scenario == "SHORT" else 0
        delivery = ensure(db, Delivery, {"delivery_no": delivery_no}, {"po_id": order.id, "supplier_id": order.supplier_id, "shipment_date": TODAY - timedelta(days=7), "expected_arrival_date": order.expected_arrival_date, "actual_arrival_date": TODAY - timedelta(days=2) if scenario != "OVERDUE" else None, "logistics_company": "华东化工物流", "tracking_no": f"YT{delivery_no[-5:]}", "status": "RECEIVED" if scenario != "OVERDUE" else "IN_TRANSIT", "received_by": users["warehouse"].id if scenario != "OVERDUE" else None, "received_at": datetime.now(timezone.utc) - timedelta(days=2) if scenario != "OVERDUE" else None}, counts)
        delivery_item = ensure(db, DeliveryItem, {"delivery_id": delivery.id, "line_no": 1}, {"po_item_id": order_item.id, "product_id": order_item.product_id, "batch_no": f"B{TODAY.strftime('%y%m')}{delivery_no[-3:]}", "package_spec": "25L/桶" if order_item.unit_id == units["L"].id else "25kg/桶", "planned_quantity": order_item.order_quantity, "actual_quantity": actual_quantity, "short_quantity": clean_decimal(short_quantity), "unit_id": order_item.unit_id, "production_date": TODAY - timedelta(days=40), "expiry_date": TODAY + timedelta(days=320), "document_complete": 1 if scenario == "FULL" else 0, "note": None}, counts)
        deliveries.append((delivery, delivery_item, scenario))
        if scenario != "OVERDUE":
            result = "PASSED" if scenario == "FULL" else "PARTIAL"
            ensure(db, QualityAcceptance, {"acceptance_no": f"QA-{delivery_no[-5:]}"}, {"delivery_id": delivery.id, "inspector_id": users["quality"].id, "result": result, "inspection_time": datetime.now(timezone.utc) - timedelta(days=1), "test_result": {"appearance": "符合要求", "identity": "合格"}, "certificate_complete": 1 if scenario == "FULL" else 0, "conclusion": "抽检结果符合采购要求。" if scenario == "FULL" else "数量短交，待供应商补发。"}, counts)
            batch = ensure(db, InventoryBatch, {"product_id": order_item.product_id, "batch_no": delivery_item.batch_no, "source_delivery_id": delivery.id}, {"supplier_id": order.supplier_id, "production_date": delivery_item.production_date, "expiry_date": delivery_item.expiry_date, "status": "ACTIVE"}, counts)
            balance = ensure(db, InventoryBalance, {"warehouse_id": warehouse.id, "location_id": location.id, "product_id": order_item.product_id, "batch_id": batch.id, "unit_id": order_item.unit_id}, {"quantity": actual_quantity, "locked_quantity": 0, "status": "AVAILABLE"}, counts)
            ensure(db, InventoryTransaction, {"transaction_no": f"IN-{delivery_no[-5:]}"}, {"transaction_type": "INBOUND", "warehouse_id": warehouse.id, "location_id": location.id, "product_id": order_item.product_id, "batch_id": batch.id, "unit_id": order_item.unit_id, "quantity": actual_quantity, "delivery_item_id": delivery_item.id, "source_type": "DELIVERY", "source_id": delivery.id, "operator_id": users["warehouse"].id, "note": None}, counts)

    exception_specs = (("EX-26001", "SHORT_DELIVERY", deliveries[1], "HIGH", "到货数量少于订单数量。", "PROCESSING"), ("EX-26002", "DOCUMENT_MISSING", deliveries[1], "MEDIUM", "到货资料未完整提供。", "OPEN"), ("EX-26003", "OVERDUE", deliveries[2], "HIGH", "采购订单超过计划到货日期仍未收货。", "OPEN"), ("EX-26004", "QUALITY", deliveries[0], "CRITICAL", "质量验收需要复核检测结果。", "CLOSED"))
    for exception_no, exception_type, (delivery, delivery_item, _), severity, description, status in exception_specs:
        exception = ensure(db, OperationException, {"exception_no": exception_no}, {"exception_type": exception_type, "source_type": "DELIVERY", "source_id": delivery.id, "po_id": delivery.po_id, "delivery_id": delivery.id, "delivery_item_id": delivery_item.id, "responsible_department_id": departments["QUALITY"].id if exception_type == "QUALITY" else departments["WAREHOUSE"].id, "owner_id": users["quality"].id if exception_type == "QUALITY" else users["warehouse"].id, "severity": severity, "description": description, "status": status, "due_at": datetime.now(timezone.utc) + timedelta(days=2), "closed_by": users["quality"].id if status == "CLOSED" else None, "closed_at": datetime.now(timezone.utc) - timedelta(days=1) if status == "CLOSED" else None, "closing_note": "已完成复核并归档。" if status == "CLOSED" else None}, counts)
        task = ensure(db, OperationTask, {"exception_id": exception.id, "title": "异常跟进"}, {"assignee_id": exception.owner_id, "priority": "HIGH" if severity in ("HIGH", "CRITICAL") else "NORMAL", "due_at": exception.due_at, "status": "COMPLETED" if status == "CLOSED" else "PROCESSING" if status == "PROCESSING" else "OPEN", "completed_at": exception.closed_at, "completion_note": "复核完成。" if status == "CLOSED" else None}, counts)
        ensure(db, OperationTaskComment, {"task_id": task.id, "commenter_id": users["buyer"].id}, {"content": "已联系相关人员跟进处理。"}, counts)
        ensure(db, Notification, {"recipient_id": exception.owner_id, "related_type": "OPERATION_EXCEPTION", "related_id": exception.id}, {"notification_type": "EXCEPTION", "title": f"异常待处理：{exception_type}", "content": description, "is_read": 1 if status == "CLOSED" else 0, "read_at": datetime.now(timezone.utc) if status == "CLOSED" else None}, counts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="获取公开化学品数据并装载开发数据")
    parser.add_argument("--public-limit", type=int, default=11, help="从 PubChem 获取的化学品数量，默认 11")
    parser.add_argument("--delay", type=float, default=0.25, help="PubChem 请求间隔秒数，不能低于 0.2")
    parser.add_argument("--dry-run", action="store_true", help="获取和清洗数据，但不写数据库")
    parser.add_argument("--skip-public", action="store_true", help="不访问 PubChem，使用数据库中已有的化学品数据")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.public_limit <= len(DEFAULT_CHEMICALS):
        raise SystemExit(f"--public-limit 必须在 1 到 {len(DEFAULT_CHEMICALS)} 之间")
    if args.delay < 0.2:
        raise SystemExit("--delay 不能低于 0.2 秒")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    public_run_dir = ROOT / "storage" / "imports" / "pubchem" / run_id
    public_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    if not args.skip_public:
        public_rows, failures = fetch_public_rows(args.public_limit, args.delay, public_run_dir)

    counts: Counter[str] = Counter()
    db = SessionLocal()
    try:
        if args.dry_run:
            print("dry_run=true")
            print(f"public_downloaded={len(public_rows)}")
            print(f"public_failed={len(failures)}")
            return
        chemical_map = upsert_public_chemicals(db, public_rows, counts) if public_rows else {}
        existing = db.scalars(select(Chemical).where(Chemical.status == "ACTIVE")).all()
        for item in existing:
            if item.cas_no:
                chemical_map.setdefault(item.cas_no, item)
        departments, users = load_organization(db, counts)
        units = load_units(db, counts)
        products, suppliers, supplier_products, warehouse, location = load_master_data(db, chemical_map, units, counts)
        load_procurement_chain(db, products, suppliers, supplier_products, units, departments, users, warehouse, location, counts)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    manifest_dir = ROOT / "storage" / "imports" / "development" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "normalized_counts.json").write_text(json.dumps({"public_downloaded": len(public_rows), "public_failed": len(failures), "created_by_table": counts, "failed_public_requests": failures}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"run_id={run_id}")
    print(f"public_downloaded={len(public_rows)}")
    print(f"public_failed={len(failures)}")
    for table_name, created_count in sorted(counts.items()):
        print(f"created_{table_name}={created_count}")
    print(f"manifest={manifest_dir}")


if __name__ == "__main__":
    main()
