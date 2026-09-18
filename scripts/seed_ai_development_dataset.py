"""扩充面向 AI 智能体开发的关联业务数据。

脚本只新增固定编号的数据，不覆盖现有记录，重复执行不会重复插入。
默认覆盖主数据、采购链路、库存作业、质量与异常、财务、知识库、行情和 AI 运行轨迹。

运行示例：
    .\\.venv\\Scripts\\python.exe scripts\\seed_ai_development_dataset.py --dry-run
    .\\.venv\\Scripts\\python.exe scripts\\seed_ai_development_dataset.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_ai_development_dataset.py --scale 2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.db import SessionLocal  # noqa: E402
from app.modules.chemicals.model import Chemical  # noqa: E402
from app.modules.deliveries.model import Delivery, DeliveryItem  # noqa: E402
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement  # noqa: E402
from app.modules.inventory.model import (  # noqa: E402
    InventoryBalance,
    InventoryIssueItem,
    InventoryIssueRequest,
    InventoryStocktakeItem,
    InventoryStocktakeRequest,
    InventoryTransaction,
    InventoryTransferItem,
    InventoryTransferRequest,
    InventoryBatch,
    Warehouse,
    WarehouseLocation,
)
from app.modules.inventory_cost.model import (  # noqa: E402
    InventoryCostAllocation,
    InventoryCostLayer,
    InventoryFifoOutboundAllocation,
    InventoryFifoOutboundRequest,
)
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest  # noqa: E402
from app.modules.notifications.model import Notification  # noqa: E402
from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment  # noqa: E402
from app.modules.products.category_model import ProductCategory  # noqa: E402
from app.modules.products.model import Product  # noqa: E402
from app.modules.purchase_orders.model import (  # noqa: E402
    PurchaseOrder,
    PurchaseOrderApproval,
    PurchaseOrderEvent,
    PurchaseOrderItem,
)
from app.modules.purchase_requests.model import (  # noqa: E402
    PurchaseRequest,
    PurchaseRequestApproval,
    PurchaseRequestItem,
    Unit,
)
from app.modules.quality_acceptances.model import QualityAcceptance  # noqa: E402
from app.modules.replenishments.model import ReplenishmentItem, ReplenishmentRequest  # noqa: E402
from app.modules.rfqs.model import (  # noqa: E402
    QuoteComparison,
    QuoteComparisonItem,
    RFQ,
    RFQItem,
    RFQSupplier,
    SupplierQuote,
    SupplierQuoteItem,
)
from app.modules.suppliers.model import Supplier  # noqa: E402
from app.modules.suppliers.product_model import SupplierProduct  # noqa: E402
from app.modules.system.file_model import SysFile, SysFileAttachment  # noqa: E402
from app.modules.system.model import Department, User  # noqa: E402
from load_development_dataset import clean_decimal, ensure, load_organization, load_units  # noqa: E402


T = TypeVar("T")
TODAY = date.today()
NOW = datetime.now(timezone.utc)


def raw_ensure(
    db: Session,
    table: str,
    where: dict[str, Any],
    values: dict[str, Any],
    counts: Counter[str],
) -> int:
    """对尚未抽象成 ORM 模型的扩展表执行幂等插入。"""

    where_sql = " AND ".join(f"`{key}` = :w_{key}" for key in where)
    params = {f"w_{key}": value for key, value in where.items()}
    existing = db.scalar(text(f"SELECT id FROM `{table}` WHERE {where_sql} LIMIT 1"), params)
    if existing is not None:
        return int(existing)
    columns = list(values)
    column_sql = ", ".join(f"`{column}`" for column in columns)
    value_sql = ", ".join(f":v_{column}" for column in columns)
    insert_params = {f"v_{column}": value for column, value in values.items()}
    db.execute(text(f"INSERT INTO `{table}` ({column_sql}) VALUES ({value_sql})"), insert_params)
    inserted_id = db.scalar(text(f"SELECT id FROM `{table}` WHERE {where_sql} LIMIT 1"), params)
    if inserted_id is None:
        raise RuntimeError(f"插入 {table} 后无法读取主键")
    counts[table] += 1
    return int(inserted_id)


def dt(days_ago: int = 0, hours_ago: int = 0) -> datetime:
    return NOW - timedelta(days=days_ago, hours=hours_ago)


def get_or_create_file(db: Session, code: str, uploader_id: int, category: str, counts: Counter[str]) -> SysFile:
    object_key = f"development/{code.lower()}.pdf"
    file_hash = hashlib.sha256(object_key.encode("utf-8")).hexdigest()
    return ensure(
        db,
        SysFile,
        {"object_key": object_key},
        {
            "file_name": f"{code}.pdf",
            "mime_type": "application/pdf",
            "file_size_bytes": 1024 + len(code) * 17,
            "sha256_hash": file_hash,
            "file_category": category,
            "access_level": "INTERNAL",
            "uploader_id": uploader_id,
            "parse_status": "SUCCEEDED",
            "parse_error": None,
            "uploaded_at": dt(len(code) % 90),
        },
        counts,
    )


def load_master_data(
    db: Session,
    units: dict[str, Unit],
    departments: dict[str, Department],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> tuple[list[Supplier], list[Product], list[Warehouse], list[WarehouseLocation]]:
    categories = db.scalars(select(ProductCategory).where(ProductCategory.status == "ACTIVE")).all()
    chemicals = db.scalars(select(Chemical).where(Chemical.status == "ACTIVE")).all()
    if not categories or not chemicals:
        raise RuntimeError("请先运行基础开发数据脚本，确保已有分类和化学品")

    suppliers = db.scalars(select(Supplier).where(Supplier.status == "ACTIVE").order_by(Supplier.id)).all()
    supplier_names = ("华东", "华南", "华北", "华中", "西南", "西北", "东北", "华东")
    industries = ("精细化工", "试剂供应链", "实验材料", "化学科技", "工业化学", "新材料")
    supplier_target = 60 * scale
    for index in range(1, supplier_target + 1):
        code = f"SUP-270{index:03d}"
        supplier = ensure(
            db,
            Supplier,
            {"supplier_code": code},
            {
                "supplier_name": f"{supplier_names[index % len(supplier_names)]}{industries[index % len(industries)]}{index:02d}",
                "unified_credit_code": f"9131{index:014d}",
                "country_code": "CN",
                "region": supplier_names[index % len(supplier_names)],
                "address": f"化工产业园 {chr(65 + index % 6)} 区 {index:02d} 号",
                "business_scope": "化学试剂、实验室耗材、危险化学品合规配送",
                "cooperation_level": ("A", "B", "C")[index % 3],
                "payment_terms": ("月结 30 天", "月结 45 天", "货到付款")[index % 3],
                "default_lead_days": 3 + index % 12,
                "status": "ACTIVE" if index % 17 else "SUSPENDED",
                "note": "季度履约评估中" if index % 11 == 0 else None,
            },
            counts,
        )
        suppliers.append(supplier)
        contact_email = f"contact{index:03d}@supplier.local"
        raw_ensure(db, "supplier_contacts", {"supplier_id": supplier.id, "email": contact_email}, {
            "supplier_id": supplier.id, "contact_name": f"联系人{index:03d}", "job_title": "客户经理",
            "phone": f"13{index % 10}{index:08d}", "email": contact_email, "is_primary": 1,
            "status": "ACTIVE",
        }, counts)
        raw_ensure(db, "supplier_contacts", {"supplier_id": supplier.id, "email": f"backup{index:03d}@supplier.local"}, {
            "supplier_id": supplier.id, "contact_name": f"协同联系人{index:03d}", "job_title": "交付专员",
            "phone": f"18{index % 10}{(index + 10000000):08d}", "email": f"backup{index:03d}@supplier.local",
            "is_primary": 0, "status": "ACTIVE",
        }, counts)
        raw_ensure(db, "supplier_qualifications", {"supplier_id": supplier.id, "qualification_type": "营业执照", "qualification_no": f"LIC-270{index:03d}"}, {
            "supplier_id": supplier.id, "qualification_type": "营业执照", "qualification_no": f"LIC-270{index:03d}",
            "issued_at": TODAY - timedelta(days=900 + index), "expires_at": TODAY + timedelta(days=300 + index),
            "review_status": "PASSED" if index % 9 else "PENDING", "reviewed_by": users["buyer"].id if index % 9 else None,
            "reviewed_at": dt(20) if index % 9 else None, "review_note": "资质材料已核验" if index % 9 else None,
        }, counts)

    suppliers = db.scalars(select(Supplier).where(Supplier.status.in_(["ACTIVE", "SUSPENDED"])).order_by(Supplier.id)).all()
    products = db.scalars(select(Product).where(Product.status == "ACTIVE").order_by(Product.id)).all()
    grades = ("AR", "GR", "CP", "分析级")
    packages = (("KG", "25kg/桶"), ("KG", "25kg/袋"), ("L", "25L/桶"), ("L", "20L/桶"), ("G", "500g/瓶"))
    product_target = 48 * scale
    for index in range(1, product_target + 1):
        chemical = chemicals[(index - 1) % len(chemicals)]
        unit_code, package = packages[index % len(packages)]
        product = ensure(
            db,
            Product,
            {"product_code": f"PRD-270{index:03d}"},
            {
                "product_name": f"{chemical.chemical_name}{grades[index % len(grades)]}-{index:02d}",
                "chemical_id": chemical.id,
                "category_id": categories[index % len(categories)].id,
                "model": grades[index % len(grades)],
                "purity_value": clean_decimal(95 + (index % 50) / 10),
                "purity_unit": "%",
                "packaging_spec": package,
                "unit_id": units[unit_code].id,
                "parameter_json": {
                    "storage_temperature": "15-25°C",
                    "certificate_required": True,
                    "hazard_label": "按化学品 SDS 执行",
                    "shelf_life_months": 12 + index % 25,
                },
                "version_no": 1,
                "status": "ACTIVE",
            },
            counts,
        )
        products.append(product)

    products = db.scalars(select(Product).where(Product.status == "ACTIVE").order_by(Product.id)).all()
    for product_index, product in enumerate(products):
        unit_id = product.unit_id
        for offset in range(4 + (product_index % 5)):
            supplier = suppliers[(product_index * 3 + offset) % len(suppliers)]
            ensure(
                db,
                SupplierProduct,
                {"supplier_id": supplier.id, "product_id": product.id},
                {
                    "supplier_model": f"{product.model or 'STD'}-{supplier.supplier_code[-3:]}",
                    "supplied_purity": product.purity_value,
                    "moq_quantity": clean_decimal(5 + (product_index + offset) % 25),
                    "moq_unit_id": unit_id,
                    "standard_lead_days": supplier.default_lead_days,
                    "capacity_note": ("常备库存", "按订单排产", "可提供分批交付")[offset % 3],
                    "status": "ACTIVE",
                },
                counts,
            )

    warehouses = db.scalars(select(Warehouse).where(Warehouse.status == "ACTIVE").order_by(Warehouse.id)).all()
    for index in range(1, 5 * scale + 1):
        warehouses.append(ensure(db, Warehouse, {"warehouse_code": f"WH-270{index:03d}"}, {
            "warehouse_name": ("华东原料仓", "华南周转仓", "北方危险品仓", "西部备件仓")[index % 4],
            "region": supplier_names[index % len(supplier_names)], "address": f"产业园仓储区 {index:02d} 号",
            "manager_id": users["warehouse"].id, "status": "ACTIVE",
        }, counts))
    locations = db.scalars(select(WarehouseLocation).where(WarehouseLocation.status == "ACTIVE").order_by(WarehouseLocation.id)).all()
    for warehouse in warehouses:
        existing = db.scalars(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse.id).order_by(WarehouseLocation.id)).all()
        if existing:
            continue
        for slot in range(1, 7):
            locations.append(ensure(db, WarehouseLocation, {"warehouse_id": warehouse.id, "location_code": f"A-{slot:02d}"}, {
                "location_name": f"A 区 {slot:02d} 货位", "status": "ACTIVE",
            }, counts))
    return suppliers, products, warehouses, locations


def load_procurement(
    db: Session,
    suppliers: list[Supplier],
    products: list[Product],
    units: dict[str, Unit],
    departments: dict[str, Department],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> tuple[list[PurchaseOrder], list[Delivery], list[InventoryBatch]]:
    request_count = 120 * scale
    rfq_count = 72 * scale
    order_count = 60 * scale
    generated_requests: list[tuple[PurchaseRequest, list[PurchaseRequestItem]]] = []
    priorities = ("NORMAL", "NORMAL", "HIGH", "URGENT")
    request_statuses = ("APPROVED", "SUBMITTED", "APPROVED", "REJECTED", "DRAFT")
    unit_codes = ("KG", "L", "G")
    for index in range(1, request_count + 1):
        applicant = users["buyer"] if index % 4 else users["warehouse"]
        status = request_statuses[index % len(request_statuses)]
        request = ensure(db, PurchaseRequest, {"request_no": f"PR-270{index:03d}"}, {
            "applicant_id": applicant.id, "department_id": departments["PROCUREMENT"].id,
            "purpose": ("研发试验原料补充", "生产线安全库存补充", "质量检测试剂采购", "仓储周转物料准备")[index % 4],
            "priority": priorities[index % len(priorities)], "budget_amount": clean_decimal(800 + index * 37),
            "currency_code": "CNY", "expected_date": TODAY + timedelta(days=5 + index % 45), "status": status,
            "submitted_at": dt(90 - index % 80), "approved_at": dt(75 - index % 60) if status == "APPROVED" else None,
            "rejected_at": dt(40) if status == "REJECTED" else None,
        }, counts)
        items: list[PurchaseRequestItem] = []
        for line_no in range(1, 1 + (2 if index % 3 else 3)):
            product = products[(index * 2 + line_no) % len(products)]
            unit = next(unit for unit in units.values() if unit.id == product.unit_id)
            quantity = clean_decimal(5 + (index * line_no) % 75)
            items.append(ensure(db, PurchaseRequestItem, {"request_id": request.id, "line_no": line_no}, {
                "product_id": product.id, "requested_name": product.product_name,
                "technical_requirements": "符合产品规格，提供 COA 和安全技术说明书",
                "quantity": quantity, "unit_id": unit.id, "budget_price": clean_decimal(12 + index % 80),
                "expected_date": request.expected_date, "fulfilled_quantity": quantity if status == "APPROVED" and index % 5 == 0 else clean_decimal(0),
                "status": "FULFILLED" if status == "APPROVED" and index % 5 == 0 else "OPEN",
            }, counts))
        for sequence, node in enumerate((("DEPARTMENT", "部门负责人"), ("PROCUREMENT", "采购负责人")), start=1):
            action = "APPROVED" if status == "APPROVED" else "REJECTED" if status == "REJECTED" and sequence == 1 else "PENDING"
            ensure(db, PurchaseRequestApproval, {"request_id": request.id, "sequence_no": sequence}, {
                "node_code": node[0], "node_name": node[1], "approver_id": users["buyer"].id if action != "PENDING" else None,
                "action": action, "opinion": "预算和用途符合要求" if action == "APPROVED" else "待审批" if action == "PENDING" else "预算需重新核对",
                "acted_at": dt(70 - index % 40) if action != "PENDING" else None,
            }, counts)
        generated_requests.append((request, items))

    rfq_context: list[tuple[RFQ, list[RFQItem], dict[int, SupplierQuote], dict[tuple[int, int], SupplierQuoteItem], QuoteComparison]] = []
    for index in range(1, rfq_count + 1):
        request, request_items = generated_requests[(index * 2) % len(generated_requests)]
        rfq_status = "CLOSED" if index % 5 == 0 else "SENT" if index % 3 else "DRAFT"
        rfq = ensure(db, RFQ, {"rfq_no": f"RFQ-270{index:03d}"}, {
            "source_request_id": request.id, "requester_id": users["buyer"].id,
            "quote_deadline": dt(3 - index % 20), "requested_delivery_date": TODAY + timedelta(days=10 + index % 35),
            "delivery_requirements": "送货至指定仓库，随货提供 COA、SDS 和批次信息", "status": rfq_status,
            "sent_at": dt(15 + index % 50) if rfq_status != "DRAFT" else None,
            "closed_at": dt(4) if rfq_status == "CLOSED" else None,
        }, counts)
        rfq_items: list[RFQItem] = []
        for line_no, request_item in enumerate(request_items[:2], start=1):
            rfq_items.append(ensure(db, RFQItem, {"rfq_id": rfq.id, "line_no": line_no}, {
                "source_request_item_id": request_item.id, "product_id": request_item.product_id,
                "requested_name": request_item.requested_name, "specification": "按采购申请规格",
                "quantity": request_item.quantity, "unit_id": request_item.unit_id,
                "required_delivery_date": request_item.expected_date, "technical_requirements": request_item.technical_requirements,
            }, counts))
        invited = [suppliers[(index * 3 + offset) % len(suppliers)] for offset in range(4)]
        quotes: dict[int, SupplierQuote] = {}
        quote_items: dict[tuple[int, int], SupplierQuoteItem] = {}
        for supplier_index, supplier in enumerate(invited):
            ensure(db, RFQSupplier, {"rfq_id": rfq.id, "supplier_id": supplier.id}, {
                "response_status": "QUOTED" if rfq_status != "DRAFT" else "PENDING",
                "response_at": dt(10) if rfq_status != "DRAFT" else None, "invitation_channel": ("EMAIL", "PORTAL", "API")[supplier_index % 3],
            }, counts)
            quote_status = "SUBMITTED" if rfq_status != "DRAFT" else "DRAFT"
            quote = ensure(db, SupplierQuote, {"quote_no": f"Q-270{index:03d}-{supplier_index + 1:02d}"}, {
                "rfq_id": rfq.id, "supplier_id": supplier.id, "quote_version": 1,
                "quote_date": TODAY - timedelta(days=8 + index % 30), "valid_until": TODAY + timedelta(days=15),
                "currency_code": "CNY", "status": quote_status, "received_by": users["buyer"].id if quote_status == "SUBMITTED" else None,
            }, counts)
            quotes[supplier.id] = quote
            for rfq_item in rfq_items:
                base = Decimal(str(10 + (rfq_item.product_id % 80)))
                price = base * (Decimal("0.94") + Decimal(str((supplier_index + index % 4) * 0.015)))
                supplier_product = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == supplier.id, SupplierProduct.product_id == rfq_item.product_id))
                if supplier_product is None:
                    supplier_product = ensure(db, SupplierProduct, {"supplier_id": supplier.id, "product_id": rfq_item.product_id}, {
                        "supplier_model": f"STD-{supplier.supplier_code[-3:]}", "supplied_purity": clean_decimal(99),
                        "moq_quantity": clean_decimal(10), "moq_unit_id": rfq_item.unit_id, "standard_lead_days": supplier.default_lead_days,
                        "capacity_note": "可按计划供货", "status": "ACTIVE",
                    }, counts)
                quote_items[(supplier.id, rfq_item.id)] = ensure(db, SupplierQuoteItem, {"quote_id": quote.id, "rfq_item_id": rfq_item.id}, {
                    "supplier_product_id": supplier_product.id, "supplier_model": supplier_product.supplier_model,
                    "quoted_quantity": rfq_item.quantity, "unit_id": rfq_item.unit_id, "unit_price": price,
                    "tax_rate": clean_decimal(13), "moq_quantity": clean_decimal(10), "moq_unit_id": rfq_item.unit_id,
                    "lead_days": supplier.default_lead_days, "payment_terms": supplier.payment_terms,
                }, counts)
        selected_supplier = invited[0]
        comparison = ensure(db, QuoteComparison, {"comparison_no": f"QC-270{index:03d}"}, {
            "rfq_id": rfq.id, "created_by": users["buyer"].id, "selected_quote_id": quotes[selected_supplier.id].id if rfq_status != "DRAFT" else None,
            "conclusion": "综合比较价格、交期、资质和历史履约记录。" if rfq_status != "DRAFT" else None,
            "selection_reason": "交期满足需求且综合成本较优。" if rfq_status != "DRAFT" else None,
            "status": "CONFIRMED" if rfq_status != "DRAFT" else "DRAFT",
            "confirmed_by": users["buyer"].id if rfq_status != "DRAFT" else None, "confirmed_at": dt(5) if rfq_status != "DRAFT" else None,
        }, counts)
        for rfq_item in rfq_items:
            for rank, supplier in enumerate(invited, start=1):
                qi = quote_items[(supplier.id, rfq_item.id)]
                ensure(db, QuoteComparisonItem, {"comparison_id": comparison.id, "quote_id": qi.quote_id, "rfq_item_id": rfq_item.id}, {
                    "supplier_id": supplier.id, "quoted_unit_price": qi.unit_price, "total_amount": qi.unit_price * qi.quoted_quantity,
                    "moq_quantity": qi.moq_quantity, "lead_days": qi.lead_days, "payment_terms": qi.payment_terms,
                    "historical_score": clean_decimal(78 + (4 - rank) * 5), "composite_score": clean_decimal(80 + (4 - rank) * 4),
                    "rank_no": rank, "selection_flag": 1 if rank == 1 and rfq_status != "DRAFT" else 0,
                }, counts)
        rfq_context.append((rfq, rfq_items, quotes, quote_items, comparison))

    orders: list[PurchaseOrder] = []
    deliveries: list[Delivery] = []
    batches: list[InventoryBatch] = []
    for index in range(1, order_count + 1):
        rfq, rfq_items, quotes, quote_items, comparison = rfq_context[(index - 1) % len(rfq_context)]
        rfq_item = rfq_items[0]
        supplier = suppliers[(index * 3) % len(suppliers)]
        quote = quotes[supplier.id]
        quote_item = quote_items[(supplier.id, rfq_item.id)]
        order_status = "COMPLETED" if index % 3 == 0 else "PARTIAL" if index % 3 == 1 else "ORDERED"
        order = ensure(db, PurchaseOrder, {"po_no": f"PO-270{index:03d}"}, {
            "supplier_id": supplier.id, "source_comparison_id": comparison.id, "source_quote_id": quote.id,
            "source_request_id": rfq.source_request_id, "department_id": departments["PROCUREMENT"].id, "buyer_id": users["buyer"].id,
            "order_amount": quote_item.unit_price * clean_decimal(quote_item.quoted_quantity), "currency_code": "CNY",
            "delivery_address": f"{supplier.region} 化学品仓储中心", "order_date": TODAY - timedelta(days=30 + index % 150),
            "expected_arrival_date": TODAY - timedelta(days=12 - index % 6), "status": order_status,
            "supplier_confirmed_at": dt(25 + index % 20), "approved_at": dt(28 + index % 20),
        }, counts)
        order_item = ensure(db, PurchaseOrderItem, {"po_id": order.id, "line_no": 1}, {
            "product_id": rfq_item.product_id, "supplier_product_id": quote_item.supplier_product_id,
            "source_quote_item_id": quote_item.id, "product_name_snapshot": rfq_item.requested_name,
            "supplier_model_snapshot": quote_item.supplier_model, "order_quantity": quote_item.quoted_quantity,
            "unit_id": rfq_item.unit_id, "unit_price": quote_item.unit_price, "tax_rate": quote_item.tax_rate,
            "planned_arrival_date": order.expected_arrival_date,
            "received_quantity": quote_item.quoted_quantity if order_status == "COMPLETED" else quote_item.quoted_quantity * Decimal("0.55") if order_status == "PARTIAL" else 0,
            "status": "COMPLETED" if order_status == "COMPLETED" else "OPEN",
        }, counts)
        for sequence, action in ((1, "APPROVED"), (2, "APPROVED")):
            ensure(db, PurchaseOrderApproval, {"po_id": order.id, "sequence_no": sequence}, {
                "node_code": "PROCUREMENT_MANAGER" if sequence == 1 else "FINANCE_MANAGER", "node_name": "采购负责人" if sequence == 1 else "财务负责人",
                "approver_id": users["buyer"].id, "action": action, "opinion": "审批通过", "acted_at": dt(27 + index % 20),
            }, counts)
        ensure(db, PurchaseOrderEvent, {"po_id": order.id, "event_type": "ORDERED"}, {
            "event_time": dt(24 + index % 20), "operator_id": users["buyer"].id, "from_status": "APPROVED", "to_status": "ORDERED", "event_note": "订单已发送供应商",
        }, counts)
        orders.append(order)
        delivery_status = "RECEIVED" if order_status != "ORDERED" else "IN_TRANSIT"
        delivery = ensure(db, Delivery, {"delivery_no": f"DLV-270{index:03d}"}, {
            "po_id": order.id, "supplier_id": supplier.id, "shipment_date": TODAY - timedelta(days=20 + index % 20),
            "expected_arrival_date": order.expected_arrival_date, "actual_arrival_date": TODAY - timedelta(days=8 + index % 5) if delivery_status == "RECEIVED" else None,
            "logistics_company": ("华化物流", "安运化工运输", "中科供应链")[index % 3], "tracking_no": f"TRK270{index:08d}",
            "status": delivery_status, "received_by": users["warehouse"].id if delivery_status == "RECEIVED" else None,
            "received_at": dt(7 + index % 5) if delivery_status == "RECEIVED" else None,
        }, counts)
        actual = order_item.received_quantity
        delivery_item = ensure(db, DeliveryItem, {"delivery_id": delivery.id, "line_no": 1}, {
            "po_item_id": order_item.id, "product_id": order_item.product_id, "batch_no": f"B270{index:05d}",
            "package_spec": "25kg/桶" if order_item.unit_id == units["KG"].id else "25L/桶",
            "planned_quantity": order_item.order_quantity, "actual_quantity": actual,
            "short_quantity": order_item.order_quantity - actual, "unit_id": order_item.unit_id,
            "production_date": TODAY - timedelta(days=80 + index % 120), "expiry_date": TODAY + timedelta(days=180 + index % 360),
            "document_complete": 1 if index % 5 else 0,
        }, counts)
        deliveries.append(delivery)
        if delivery_status == "RECEIVED":
            result = "PASSED" if index % 7 else "PARTIAL"
            ensure(db, QualityAcceptance, {"acceptance_no": f"QA-270{index:03d}"}, {
                "delivery_id": delivery.id, "inspector_id": users["quality"].id, "result": result,
                "inspection_time": dt(6 + index % 5), "test_result": {"appearance": "符合要求" if result == "PASSED" else "需复检", "identity": "合格", "purity": str(98 + index % 20 / 10)},
                "certificate_complete": 1 if index % 5 else 0, "conclusion": "抽检结果符合采购要求。" if result == "PASSED" else "部分资料待补充并复核。",
            }, counts)
            warehouse = db.scalar(select(Warehouse).order_by(Warehouse.id))
            location = db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse.id).order_by(WarehouseLocation.id))
            batch = ensure(db, InventoryBatch, {"product_id": order_item.product_id, "batch_no": delivery_item.batch_no, "source_delivery_id": delivery.id}, {
                "supplier_id": supplier.id, "production_date": delivery_item.production_date, "expiry_date": delivery_item.expiry_date, "status": "ACTIVE",
            }, counts)
            batches.append(batch)
            balance = ensure(db, InventoryBalance, {"warehouse_id": warehouse.id, "location_id": location.id, "product_id": order_item.product_id, "batch_id": batch.id, "unit_id": order_item.unit_id}, {
                "quantity": actual + clean_decimal(10 + index % 20), "locked_quantity": clean_decimal(index % 5), "status": "AVAILABLE",
            }, counts)
            inbound = ensure(db, InventoryTransaction, {"transaction_no": f"IN-270{index:03d}"}, {
                "transaction_type": "INBOUND", "warehouse_id": warehouse.id, "location_id": location.id,
                "product_id": order_item.product_id, "batch_id": batch.id, "unit_id": order_item.unit_id, "quantity": actual,
                "delivery_item_id": delivery_item.id, "source_type": "DELIVERY", "source_id": delivery.id, "operator_id": users["warehouse"].id,
            }, counts)
            layer = ensure(db, InventoryCostLayer, {"source_transaction_id": inbound.id}, {
                "warehouse_id": warehouse.id, "location_id": location.id, "product_id": order_item.product_id, "batch_id": batch.id,
                "unit_id": order_item.unit_id, "unit_cost": quote_item.unit_price, "currency_code": "CNY",
                "original_quantity": actual, "remaining_quantity": actual,
            }, counts)
    return orders, deliveries, batches


def load_inventory_workflows(
    db: Session,
    products: list[Product],
    warehouses: list[Warehouse],
    locations: list[WarehouseLocation],
    batches: list[InventoryBatch],
    departments: dict[str, Department],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> None:
    if not batches:
        return
    work_count = 50 * scale
    for index in range(1, work_count + 1):
        batch = batches[(index - 1) % len(batches)]
        product = db.get(Product, batch.product_id)
        unit_id = product.unit_id
        warehouse = warehouses[index % len(warehouses)]
        location = next((item for item in locations if item.warehouse_id == warehouse.id), locations[0])
        status = ("COMPLETED", "APPROVED", "SUBMITTED", "REJECTED", "DRAFT")[index % 5]
        issue = ensure(db, InventoryIssueRequest, {"issue_no": f"ISS-270{index:03d}"}, {
            "applicant_id": users["buyer"].id, "department_id": departments["R_AND_D"].id if "R_AND_D" in departments else departments["PROCUREMENT"].id,
            "purpose": ("研发试验领用", "质量抽检领用", "生产小试领用")[index % 3], "status": status,
            "approved_by": users["warehouse"].id if status in {"COMPLETED", "APPROVED"} else None,
            "approved_at": dt(10) if status in {"COMPLETED", "APPROVED"} else None, "completed_at": dt(5) if status == "COMPLETED" else None,
        }, counts)
        requested = clean_decimal(2 + index % 12)
        ensure(db, InventoryIssueItem, {"issue_request_id": issue.id, "line_no": 1}, {
            "product_id": product.id, "warehouse_id": warehouse.id, "location_id": location.id, "batch_id": batch.id,
            "unit_id": unit_id, "requested_quantity": requested, "issued_quantity": requested if status == "COMPLETED" else clean_decimal(0),
            "status": "COMPLETED" if status == "COMPLETED" else "OPEN",
        }, counts)
        transfer = ensure(db, InventoryTransferRequest, {"transfer_no": f"TRF-270{index:03d}"}, {
            "applicant_id": users["warehouse"].id, "purpose": "跨仓库存调拨", "status": status,
            "approved_by": users["warehouse"].id if status in {"COMPLETED", "APPROVED"} else None,
            "approved_at": dt(9) if status in {"COMPLETED", "APPROVED"} else None, "completed_at": dt(4) if status == "COMPLETED" else None,
        }, counts)
        target_warehouse = warehouses[(index + 1) % len(warehouses)]
        target_location = next((item for item in locations if item.warehouse_id == target_warehouse.id), locations[0])
        transferred = clean_decimal(1 + index % 9) if status == "COMPLETED" else clean_decimal(0)
        ensure(db, InventoryTransferItem, {"transfer_request_id": transfer.id, "line_no": 1}, {
            "product_id": product.id, "source_warehouse_id": warehouse.id, "source_location_id": location.id,
            "target_warehouse_id": target_warehouse.id, "target_location_id": target_location.id, "batch_id": batch.id, "unit_id": unit_id,
            "requested_quantity": clean_decimal(10 + index % 15), "transferred_quantity": transferred,
            "status": "COMPLETED" if status == "COMPLETED" else "OPEN",
        }, counts)
        stocktake = ensure(db, InventoryStocktakeRequest, {"stocktake_no": f"STK-270{index:03d}"}, {
            "applicant_id": users["warehouse"].id, "warehouse_id": warehouse.id, "location_id": location.id,
            "purpose": "月度库存盘点", "status": status, "approved_by": users["warehouse"].id if status in {"COMPLETED", "APPROVED"} else None,
            "approved_at": dt(8) if status in {"COMPLETED", "APPROVED"} else None, "completed_at": dt(3) if status == "COMPLETED" else None,
        }, counts)
        book = clean_decimal(20 + index % 30)
        counted = book + clean_decimal(-1 if index % 6 == 0 else 0 if index % 3 else 1)
        ensure(db, InventoryStocktakeItem, {"stocktake_request_id": stocktake.id, "line_no": 1}, {
            "product_id": product.id, "location_id": location.id, "batch_id": batch.id, "unit_id": unit_id,
            "book_quantity": book, "counted_quantity": counted, "difference_quantity": counted - book,
            "status": "COMPLETED" if status == "COMPLETED" else "OPEN",
        }, counts)
        return_request = ensure(db, InventoryReturnRequest, {"return_no": f"RET-270{index:03d}"}, {
            "supplier_id": db.scalar(select(Supplier.id).order_by(Supplier.id)), "po_id": None, "delivery_id": None,
            "applicant_id": users["warehouse"].id, "reason": "质量复检后退回供应商", "status": status,
            "approved_by": users["quality"].id if status in {"COMPLETED", "APPROVED"} else None,
            "approved_at": dt(7) if status in {"COMPLETED", "APPROVED"} else None, "completed_at": dt(2) if status == "COMPLETED" else None,
        }, counts)
        ensure(db, InventoryReturnItem, {"return_request_id": return_request.id, "line_no": 1}, {
            "product_id": product.id, "warehouse_id": warehouse.id, "location_id": location.id, "batch_id": batch.id, "unit_id": unit_id,
            "requested_quantity": clean_decimal(2 + index % 5), "returned_quantity": clean_decimal(2 + index % 5) if status == "COMPLETED" else clean_decimal(0),
            "status": "COMPLETED" if status == "COMPLETED" else "OPEN",
        }, counts)
        replenishment = ensure(db, ReplenishmentRequest, {"replenishment_no": f"REP-270{index:03d}"}, {
            "supplier_id": db.scalar(select(Supplier.id).order_by(Supplier.id)), "source_po_id": None, "source_delivery_id": None,
            "applicant_id": users["buyer"].id, "reason": "安全库存低于补货阈值", "status": status,
            "approved_by": users["buyer"].id if status in {"COMPLETED", "APPROVED"} else None,
            "approved_at": dt(6) if status in {"COMPLETED", "APPROVED"} else None, "completed_at": dt(1) if status == "COMPLETED" else None,
        }, counts)
        ensure(db, ReplenishmentItem, {"replenishment_request_id": replenishment.id, "line_no": 1}, {
            "product_id": product.id, "unit_id": unit_id, "requested_quantity": clean_decimal(10 + index % 20),
            "expected_date": TODAY + timedelta(days=4 + index % 15), "status": "COMPLETED" if status == "COMPLETED" else "OPEN",
        }, counts)

        fifo = ensure(db, InventoryFifoOutboundRequest, {"request_no": f"FIFO-270{index:03d}"}, {
            "product_id": product.id, "warehouse_id": warehouse.id, "location_id": location.id, "unit_id": unit_id,
            "requested_quantity": clean_decimal(1 + index % 8), "issued_quantity": clean_decimal(1 + index % 8) if status == "COMPLETED" else clean_decimal(0),
            "total_cost": clean_decimal((1 + index % 8) * (12 + index % 30)), "currency_code": "CNY", "status": "COMPLETED" if status == "COMPLETED" else "PENDING",
            "operator_id": users["warehouse"].id,
        }, counts)
        layer = db.scalar(select(InventoryCostLayer).where(InventoryCostLayer.batch_id == batch.id).order_by(InventoryCostLayer.id))
        if layer and status == "COMPLETED":
            ensure(db, InventoryFifoOutboundAllocation, {"request_id": fifo.id, "cost_layer_id": layer.id}, {
                "batch_id": batch.id, "quantity": fifo.issued_quantity, "unit_cost": layer.unit_cost, "total_cost": fifo.total_cost,
            }, counts)


def load_quality_and_finance(
    db: Session,
    orders: list[PurchaseOrder],
    suppliers: list[Supplier],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> None:
    for index, order in enumerate(orders, start=1):
        supplier = db.get(Supplier, order.supplier_id)
        amount = order.order_amount
        reconciliation = ensure(db, FinanceReconciliation, {"po_id": order.id}, {
            "reconciliation_no": f"REC-270{index:03d}", "supplier_id": supplier.id, "currency_code": "CNY", "total_amount": amount,
            "status": "CLOSED" if index % 4 == 0 else "CONFIRMED", "created_by": users["buyer"].id,
            "confirmed_by": users["buyer"].id, "confirmed_at": dt(5), "closed_at": dt(2) if index % 4 == 0 else None,
        }, counts)
        invoice_amount = amount / Decimal("1.13")
        invoice = ensure(db, FinanceInvoice, {"invoice_no": f"INV-270{index:03d}"}, {
            "reconciliation_id": reconciliation.id, "po_id": order.id, "supplier_id": supplier.id,
            "invoice_code": f"3100{index:08d}", "invoice_number": f"880270{index:08d}", "invoice_date": TODAY - timedelta(days=3 + index % 30),
            "amount_excl_tax": invoice_amount, "tax_amount": amount - invoice_amount, "amount_incl_tax": amount, "currency_code": "CNY",
            "status": "VERIFIED" if index % 4 else "SUBMITTED", "submitted_by": users["buyer"].id,
            "verified_by": users["buyer"].id if index % 4 else None, "verified_at": dt(2) if index % 4 else None,
        }, counts)
        payment_status = "PAID" if index % 3 == 0 else "APPROVED" if index % 3 == 1 else "REQUESTED"
        ensure(db, FinancePayment, {"payment_no": f"PAY-270{index:03d}"}, {
            "reconciliation_id": reconciliation.id, "po_id": order.id, "supplier_id": supplier.id, "amount": amount,
            "currency_code": "CNY", "payment_method": ("银行转账", "网银支付")[index % 2], "status": payment_status,
            "requested_by": users["buyer"].id, "approved_by": users["buyer"].id if payment_status in {"PAID", "APPROVED"} else None,
            "paid_by": users["buyer"].id if payment_status == "PAID" else None,
            "approved_at": dt(2) if payment_status in {"PAID", "APPROVED"} else None, "paid_at": dt(1) if payment_status == "PAID" else None,
            "transaction_ref": f"BANK270{index:010d}" if payment_status == "PAID" else None,
        }, counts)
        ensure(db, FinanceSettlement, {"settlement_no": f"SET-270{index:03d}"}, {
            "reconciliation_id": reconciliation.id, "po_id": order.id, "supplier_id": supplier.id, "settlement_amount": amount,
            "currency_code": "CNY", "status": "CONFIRMED" if index % 3 == 0 else "DRAFT", "created_by": users["buyer"].id,
            "confirmed_by": users["buyer"].id if index % 3 == 0 else None, "confirmed_at": dt(1) if index % 3 == 0 else None,
        }, counts)


def load_exceptions_notifications(
    db: Session,
    orders: list[PurchaseOrder],
    deliveries: list[Delivery],
    departments: dict[str, Department],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> None:
    exception_count = 120 * scale
    types = ("SHORT_DELIVERY", "DOCUMENT_MISSING", "OVERDUE", "QUALITY", "LOW_STOCK", "PRICE_CHANGE")
    severities = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    for index in range(1, exception_count + 1):
        delivery = deliveries[(index - 1) % len(deliveries)]
        order = orders[(index - 1) % len(orders)]
        status = ("OPEN", "PROCESSING", "CLOSED", "OPEN")[index % 4]
        owner = users["quality"] if index % 3 == 0 else users["warehouse"]
        exception = ensure(db, OperationException, {"exception_no": f"EX-270{index:03d}"}, {
            "exception_type": types[index % len(types)], "source_type": "DELIVERY", "source_id": delivery.id,
            "po_id": order.id, "delivery_id": delivery.id, "delivery_item_id": None,
            "responsible_department_id": departments["QUALITY"].id if owner.username == "quality" else departments["WAREHOUSE"].id,
            "owner_id": owner.id, "severity": severities[index % len(severities)],
            "description": ("到货数量与采购订单存在差异。", "随货质量文件尚未齐全。", "计划到货日期已超期。", "质检结果需要复核。", "库存低于安全阈值。", "近期报价波动需要关注。")[index % 6],
            "status": status, "due_at": dt(-2 if status == "OPEN" else 3),
            "closed_by": owner.id if status == "CLOSED" else None, "closed_at": dt(1) if status == "CLOSED" else None,
            "closing_note": "已完成处理并归档。" if status == "CLOSED" else None,
        }, counts)
        task = ensure(db, OperationTask, {"exception_id": exception.id, "title": "异常核查与跟进"}, {
            "assignee_id": owner.id, "priority": "HIGH" if exception.severity in {"HIGH", "CRITICAL"} else "NORMAL",
            "due_at": exception.due_at, "status": "COMPLETED" if status == "CLOSED" else "PROCESSING" if status == "PROCESSING" else "OPEN",
            "completed_at": exception.closed_at, "completion_note": "核查完成。" if status == "CLOSED" else None,
        }, counts)
        for commenter in (users["buyer"], owner):
            ensure(db, OperationTaskComment, {"task_id": task.id, "commenter_id": commenter.id}, {
                "content": "已记录处理进展，等待下一节点确认。" if status != "CLOSED" else "结果已确认并完成归档。",
            }, counts)
        ensure(db, Notification, {"recipient_id": owner.id, "related_type": "OPERATION_EXCEPTION", "related_id": exception.id}, {
            "notification_type": "EXCEPTION", "title": f"运营异常待处理：{types[index % len(types)]}",
            "content": exception.description, "is_read": 1 if status == "CLOSED" else 0, "read_at": dt(1) if status == "CLOSED" else None,
        }, counts)


def load_knowledge_market_ai(
    db: Session,
    products: list[Product],
    suppliers: list[Supplier],
    users: dict[str, User],
    counts: Counter[str],
    scale: int,
) -> None:
    documents = []
    for index in range(1, 96 * scale + 1):
        product = products[(index - 1) % len(products)]
        supplier = suppliers[(index * 2) % len(suppliers)]
        category = ("SDS", "TDS", "COA", "QUOTE", "QUALIFICATION")[index % 5]
        file = get_or_create_file(db, f"DOC-270{index:03d}", users["buyer"].id, category, counts)
        document_id = raw_ensure(db, "knowledge_documents", {"file_id": file.id}, {
            "file_id": file.id, "title": f"{product.product_name}-{category}资料", "document_type": category,
            "version_label": f"V{1 + index % 4}", "source_name": supplier.supplier_name,
            "published_at": TODAY - timedelta(days=30 + index % 500), "effective_from": TODAY - timedelta(days=20 + index % 300),
            "expires_at": TODAY + timedelta(days=90 + index % 400), "chemical_id": product.chemical_id, "product_id": product.id,
            "supplier_id": supplier.id, "confirmation_status": "CONFIRMED" if index % 6 else "UNCONFIRMED",
            "confirmed_by": users["quality"].id if index % 6 else None, "confirmed_at": dt(10) if index % 6 else None, "status": "ACTIVE",
        }, counts)
        documents.append((document_id, product))
        for chunk_no in range(1, 1 + (3 if index % 4 else 5)):
            raw_ensure(db, "knowledge_document_chunks", {"document_id": document_id, "chunk_no": chunk_no}, {
                "document_id": document_id, "chunk_no": chunk_no, "page_no": chunk_no,
                "section_path": ("产品信息/基本性质", "质量要求/检验项目", "储存与运输/安全要求", "采购条款/交付要求")[chunk_no % 4],
                "content": f"{product.product_name} 的第 {chunk_no} 个资料片段：采购时应核对批次、纯度、包装、有效期和随货文件，入库前按质量标准完成验收。",
                "extracted_fields": json.dumps({"product_id": product.id, "document_type": category, "required_checks": ["批次", "纯度", "有效期"]}, ensure_ascii=False),
                "source_locator": f"page:{chunk_no}", "confirmation_status": "CONFIRMED" if index % 6 else "UNCONFIRMED",
                "vector_ref": f"chunk-{document_id}-{chunk_no}",
            }, counts)
        raw_ensure(db, "sys_file_attachments", {"resource_type": "KNOWLEDGE_DOCUMENT", "resource_id": document_id, "file_id": file.id}, {
            "file_id": file.id, "resource_type": "KNOWLEDGE_DOCUMENT", "resource_id": document_id, "created_by": users["buyer"].id,
        }, counts)

    for index in range(1, 1001 * scale + 1):
        product = products[(index - 1) % len(products)]
        supplier = suppliers[(index * 5) % len(suppliers)]
        unit_id = product.unit_id
        price = clean_decimal(8 + (product.id % 70) + (index % 25) / 10)
        raw_ensure(db, "market_price_records", {"source_ref": f"PRICE-270{index:05d}"}, {
            "product_id": product.id, "supplier_id": supplier.id, "quote_date": TODAY - timedelta(days=index % 730),
            "quantity_from": clean_decimal(1), "quantity_to": clean_decimal(10 + index % 90), "unit_id": unit_id,
            "price": price, "currency_code": "CNY", "source_type": ("QUOTE", "PUBLIC", "IMPORT")[index % 3],
            "source_ref": f"PRICE-270{index:05d}", "quality_status": "VALID" if index % 13 else "UNREVIEWED",
        }, counts)

    for index in range(1, 49 * scale + 1):
        product = products[(index - 1) % len(products)]
        run_id = raw_ensure(db, "price_forecast_runs", {"product_id": product.id, "model_version": f"forecast-v1-{index:03d}"}, {
            "product_id": product.id, "train_start_date": TODAY - timedelta(days=365), "train_end_date": TODAY - timedelta(days=1),
            "model_version": f"forecast-v1-{index:03d}", "forecast_horizon_days": 30, "status": "SUCCEEDED",
            "started_at": dt(1, index % 8), "finished_at": dt(1), "created_by": users["buyer"].id,
        }, counts)
        for day in range(1, 31):
            predicted = clean_decimal(8 + product.id % 70 + (index % 10) / 10 + day / 20)
            raw_ensure(db, "price_forecast_items", {"run_id": run_id, "forecast_date": TODAY + timedelta(days=day)}, {
                "run_id": run_id, "forecast_date": TODAY + timedelta(days=day), "predicted_price": predicted,
                "lower_bound": predicted * Decimal("0.92"), "upper_bound": predicted * Decimal("1.08"), "confidence": Decimal("0.82"),
                "explanation": "基于历史报价、供应商交期和近期价格波动生成预测。",
            }, counts)

    scenes = ("PRODUCT_SEARCH", "QUOTE_COMPARE", "INVENTORY_ALERT", "EXCEPTION_HANDLE", "PURCHASE_PLAN")
    for index in range(1, 51 * scale + 1):
        user = users["buyer"] if index % 3 else users["quality"]
        conversation_id = raw_ensure(db, "ai_conversations", {"user_id": user.id, "title": f"业务分析会话{index:03d}"}, {
            "user_id": user.id, "title": f"业务分析会话{index:03d}", "business_scene": scenes[index % len(scenes)],
            "permission_snapshot": json.dumps({"role": "业务用户", "resources": ["product", "supplier", "inventory", "purchase"]}, ensure_ascii=False),
            "status": "CLOSED" if index % 4 == 0 else "ACTIVE", "last_message_at": dt(index % 30),
        }, counts)
        user_message_id = raw_ensure(db, "ai_messages", {"conversation_id": conversation_id, "message_role": "USER", "content": f"请分析第{index:03d}组业务数据"}, {
            "conversation_id": conversation_id, "message_role": "USER", "content": f"请分析第{index:03d}组业务数据",
            "citations": json.dumps([], ensure_ascii=False), "created_at": dt(index % 30, 2),
        }, counts)
        raw_ensure(db, "ai_messages", {"conversation_id": conversation_id, "message_role": "ASSISTANT", "content": f"已完成第{index:03d}组业务数据的关联分析"}, {
            "conversation_id": conversation_id, "message_role": "ASSISTANT", "content": f"已完成第{index:03d}组业务数据的关联分析",
            "citations": json.dumps([{"type": "product", "id": products[(index - 1) % len(products)].id}], ensure_ascii=False), "created_at": dt(index % 30),
        }, counts)
        run_id = raw_ensure(db, "ai_runs", {"conversation_id": conversation_id, "input_summary": f"分析任务-{index:03d}"}, {
            "conversation_id": conversation_id, "trigger_message_id": user_message_id, "model_name": "agent-development-model",
            "status": "SUCCEEDED" if index % 8 else "FAILED", "started_at": dt(index % 30, 1), "finished_at": dt(index % 30),
            "duration_ms": 850 + index * 7, "error_message": "工具返回超时" if index % 8 == 0 else None,
            "input_summary": f"分析任务-{index:03d}", "output_summary": "已整理产品、供应商、库存和采购建议。",
        }, counts)
        for step_no, step_name in enumerate(("识别业务意图", "检索业务数据", "核对关联关系", "生成处理建议"), start=1):
            step_id = raw_ensure(db, "ai_run_steps", {"run_id": run_id, "step_no": step_no}, {
                "run_id": run_id, "step_no": step_no, "step_name": step_name, "status": "SUCCEEDED" if index % 8 else "FAILED",
                "input_summary": "读取当前上下文和权限范围", "output_summary": "返回结构化业务结果",
                "duration_ms": 120 + step_no * 35, "started_at": dt(index % 30, 1), "finished_at": dt(index % 30),
            }, counts)
            tool_id = raw_ensure(db, "ai_tool_calls", {"run_step_id": step_id, "tool_name": ("search_products", "search_suppliers", "check_inventory", "draft_action")[step_no - 1]}, {
                "run_step_id": step_id, "tool_name": ("search_products", "search_suppliers", "check_inventory", "draft_action")[step_no - 1],
                "arguments_json": json.dumps({"product_id": products[(index - 1) % len(products)].id}, ensure_ascii=False),
                "permission_status": "ALLOWED", "permission_snapshot": json.dumps({"allowed": True}, ensure_ascii=False),
                "result_summary": "返回匹配记录和关键字段", "status": "SUCCEEDED" if index % 8 else "FAILED",
                "started_at": dt(index % 30), "finished_at": dt(index % 30), "duration_ms": 80 + step_no * 20,
            }, counts)
            if step_no == 4:
                raw_ensure(db, "ai_action_approvals", {"tool_call_id": tool_id}, {
                    "tool_call_id": tool_id, "action_type": "CREATE_PURCHASE_PLAN", "target_type": "PRODUCT",
                    "target_id": products[(index - 1) % len(products)].id,
                    "draft_payload": json.dumps({"product_id": products[(index - 1) % len(products)].id, "quantity": 20, "unit": "KG"}, ensure_ascii=False),
                    "status": "APPROVED" if index % 3 == 0 else "PENDING", "requested_by": user.id,
                    "approved_by": user.id if index % 3 == 0 else None, "requested_at": dt(index % 30),
                    "approved_at": dt(index % 30) if index % 3 == 0 else None,
                    "approval_comment": "建议与当前库存和交期匹配。" if index % 3 == 0 else None,
                    "execution_result": json.dumps({"status": "待执行"}, ensure_ascii=False) if index % 3 else json.dumps({"status": "已生成采购计划"}, ensure_ascii=False),
                }, counts)

    for index in range(1, 501 * scale + 1):
        resource_type = ("PURCHASE_ORDER", "DELIVERY", "INVENTORY_BALANCE", "KNOWLEDGE_DOCUMENT")[index % 4]
        resource_id = products[(index - 1) % len(products)].id
        audit_action = ("VIEW", "SEARCH", "EXPORT", "UPDATE")[index % 4]
        request_summary = f"访问业务记录{index:04d}"
        raw_ensure(db, "sys_audit_logs", {"actor_id": users["buyer"].id, "action_type": audit_action, "resource_type": resource_type, "resource_id": resource_id, "request_summary": request_summary}, {
            "actor_id": users["buyer"].id, "action_type": audit_action,
            "resource_type": resource_type, "resource_id": resource_id, "request_summary": request_summary,
            "result_status": "SUCCESS" if index % 19 else "DENIED", "ip_address": f"10.20.{index % 30}.{index % 240 + 1}",
            "user_agent": "ChemicalOps Desktop Client",
        }, counts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="扩充面向 AI 智能体开发的关联业务数据")
    parser.add_argument("--scale", type=int, default=1, help="数据规模倍数，默认 1")
    parser.add_argument("--dry-run", action="store_true", help="仅检查数据库和规模，不写入")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.scale < 1 or args.scale > 5:
        raise SystemExit("--scale 必须在 1 到 5 之间")
    counts: Counter[str] = Counter()
    db = SessionLocal()
    try:
        departments, users = load_organization(db, counts)
        units = load_units(db, counts)
        if args.dry_run:
            print(f"dry_run=true scale={args.scale}")
            print(f"planned_suppliers={60 * args.scale}")
            print(f"planned_products={48 * args.scale}")
            print(f"planned_purchase_requests={120 * args.scale}")
            print(f"planned_market_prices={1000 * args.scale}")
            print(f"planned_ai_conversations={50 * args.scale}")
            return
        suppliers, products, warehouses, locations = load_master_data(db, units, departments, users, counts, args.scale)
        orders, deliveries, batches = load_procurement(db, suppliers, products, units, departments, users, counts, args.scale)
        load_inventory_workflows(db, products, warehouses, locations, batches, departments, users, counts, args.scale)
        load_quality_and_finance(db, orders, suppliers, users, counts, args.scale)
        load_exceptions_notifications(db, orders, deliveries, departments, users, counts, args.scale)
        load_knowledge_market_ai(db, products, suppliers, users, counts, args.scale)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = ROOT / "storage" / "imports" / "development" / f"ai_dataset_{run_id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "normalized_counts.json").write_text(json.dumps({"scale": args.scale, "created_by_table": counts}, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    print(f"run_id={run_id}")
    print(f"created_total={sum(counts.values())}")
    for table_name, created_count in sorted(counts.items()):
        print(f"created_{table_name}={created_count}")
    print(f"manifest={report_dir}")


if __name__ == "__main__":
    main()
