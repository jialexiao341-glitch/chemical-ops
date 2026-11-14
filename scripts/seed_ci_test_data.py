"""为 CI 与隔离测试库离线构造完整业务样本数据。

用途：
1. 仅使用仓库内静态化学品、主数据、采购履约、质量复核、财务对账与文档片段，不发起任何外网请求；
2. 覆盖多部门采购订单、部分到货/短交/超期异常、库存成本层与领用/调拨/盘点/补货/退货、质量报告复核与文档知识库；
3. 支持幂等重复执行，不覆盖或重复扣减已生成的事务性库存与财务单据。

安全边界：
- 默认禁止向开发库 `chemicalops` 写入 CI 样本数据，仅允许在 `CI=true`、`APP_ENV in {test,testing,ci}` 或显式 `--allow-isolated-test-db` 下执行。
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.chemicals_master.model import Chemical  # noqa: E402
from app.modules.deliveries_receipt.model import Delivery, DeliveryItem  # noqa: E402
from app.modules.doc_kb.model import AiDocument, AiDocumentSection  # noqa: E402
from app.modules.files_storage import service as file_service  # noqa: E402
from app.modules.finance_management import invoice_matches, service as finance_service  # noqa: E402
from app.modules.finance_management.model import FinanceInvoice, FinanceReconciliation  # noqa: E402
from app.modules.finance_management.schema import InvoiceAllocation, InvoiceCreate, InvoiceMatchSave  # noqa: E402
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer  # noqa: E402
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest  # noqa: E402
from app.modules.inventory_stock.model import (  # noqa: E402
    InventoryBalance,
    InventoryBatch,
    InventoryIssueItem,
    InventoryIssueRequest,
    InventoryStocktakeItem,
    InventoryStocktakeRequest,
    InventoryTransaction,
    InventoryTransferItem,
    InventoryTransferRequest,
    Warehouse,
    WarehouseLocation,
)
from app.modules.notifications_center.model import Notification  # noqa: E402
from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment  # noqa: E402
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem  # noqa: E402
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestApproval, PurchaseRequestItem  # noqa: E402
from app.modules.quality_acceptances.model import QualityAcceptance, QualityReportReviewRecord  # noqa: E402
from app.modules.quality_acceptances.schema import QualityReportCheck, QualityReportReview  # noqa: E402
from app.modules.replenishment_plans.model import ReplenishmentItem, ReplenishmentRequest  # noqa: E402
from app.modules.rfq_quotes.model import (  # noqa: E402
    QuoteComparison,
    QuoteComparisonItem,
    RFQ,
    RFQItem,
    RFQSupplier,
    SupplierQuote,
    SupplierQuoteItem,
)
from app.modules.suppliers_master.model import Supplier  # noqa: E402
from app.modules.suppliers_master.product_model import SupplierProduct  # noqa: E402
from app.modules.system_management.crud import get_user_role_codes  # noqa: E402
from app.modules.system_management.file_model import SysFile, SysFileAttachment  # noqa: E402
from app.modules.system_management.model import (  # noqa: E402
    Department,
    User,
    UserWarehouseGrant,
    UserWarehouseScope,
)
from load_development_dataset import (  # noqa: E402
    clean_decimal,
    ensure,
    load_master_data,
    load_units,
)


TODAY = date.today()
NOW = datetime.now(timezone.utc)

# 离线静态化学品清单，对应 load_master_data 所需的 8 种常用化学试剂。
OFFLINE_CHEMICALS: tuple[tuple[str, str, str, str, Decimal, str], ...] = (
    ("乙醇", "Ethanol", "64-17-5", "C2H6O", Decimal("46.070000"), "易燃液体"),
    ("甲醇", "Methanol", "67-56-1", "CH4O", Decimal("32.040000"), "易燃液体"),
    ("丙酮", "Acetone", "67-64-1", "C3H6O", Decimal("58.080000"), "易燃液体"),
    ("乙酸", "Acetic acid", "64-19-7", "C2H4O2", Decimal("60.050000"), "腐蚀性液体"),
    ("盐酸", "Hydrochloric acid", "7647-01-0", "HCl", Decimal("36.460000"), "酸性腐蚀品"),
    ("硫酸", "Sulfuric acid", "7664-93-9", "H2SO4", Decimal("98.080000"), "酸性腐蚀品"),
    ("氢氧化钠", "Sodium hydroxide", "1310-73-2", "NaOH", Decimal("40.000000"), "碱性腐蚀品"),
    ("过氧化氢", "Hydrogen peroxide", "7722-84-1", "H2O2", Decimal("34.010000"), "氧化剂"),
)

_MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _ensure_safe_target(allow_isolated_test_db: bool) -> None:
    """校验当前目标数据库是否为 CI 或隔离测试库，避免误写本地开发库。"""

    settings = get_settings()
    in_ci = os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}
    env_ok = settings.app_env.strip().lower() in {"test", "testing", "ci"}
    if settings.mysql_database == "chemicalops" and not (in_ci or env_ok or allow_isolated_test_db):
        raise SystemExit(
            "拒绝向默认开发库 chemicalops 写入 CI 样本数据；"
            "请切换 MYSQL_DATABASE 到隔离测试库或显式传入 --allow-isolated-test-db"
        )


def _load_org_context(db: Session) -> tuple[dict[str, Department], dict[str, User]]:
    """读取已由 seed_demo_accounts 创建的部门和账号，并补充关键部门负责人。"""

    required_depts = ("PROCUREMENT", "QUALITY", "WAREHOUSE", "R_AND_D", "FINANCE", "MANAGEMENT")
    departments: dict[str, Department] = {}
    for code in required_depts:
        dept = db.scalar(select(Department).where(Department.department_code == code))
        if dept is None:
            raise RuntimeError(f"缺少必需部门 {code}，请先执行 seed_demo_accounts.py")
        departments[code] = dept

    required_users = (
        "SystemAdmin",
        "ProcManager",
        "BuyerUser",
        "TechEngineer",
        "WarehouseUser",
        "QualityInspector",
        "QualityManager",
        "FinanceClerk",
        "FinanceManager",
    )
    users: dict[str, User] = {}
    for username in required_users:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            raise RuntimeError(f"缺少必需账号 {username}，请先执行 seed_demo_accounts.py")
        users[username] = user

    for dept_code, manager_username in (
        ("PROCUREMENT", "BuyerUser"),
        ("QUALITY", "QualityInspector"),
        ("WAREHOUSE", "WarehouseUser"),
    ):
        if departments[dept_code].manager_id is None:
            departments[dept_code].manager_id = users[manager_username].id
    db.flush()
    return departments, users


def _seed_offline_chemicals(db: Session, counts: Counter[str]) -> dict[str, Chemical]:
    """幂等写入静态化学品基础信息，避免在 CI 中依赖 PubChem 网络。"""

    chemical_map: dict[str, Chemical] = {}
    for chemical_name, english_name, cas_no, formula, weight, hazard in OFFLINE_CHEMICALS:
        chemical = ensure(
            db,
            Chemical,
            {"cas_no": cas_no},
            {
                "chemical_name": chemical_name,
                "english_name": english_name,
                "chemical_formula": formula,
                "molecular_weight": weight,
                "hazard_class": hazard,
                "source_text": "CI offline curated chemical reference",
                "status": "ACTIVE",
            },
            counts,
        )
        chemical_map[cas_no] = chemical
    return chemical_map


def _seed_procurement_chain(
    db: Session,
    products: dict,
    suppliers: dict[str, Supplier],
    supplier_products: dict[tuple[str, str], SupplierProduct],
    units: dict,
    departments: dict[str, Department],
    users: dict[str, User],
    warehouse: Warehouse,
    location: WarehouseLocation,
    counts: Counter[str],
) -> None:
    """幂等构造符合唯一比价单来源约束的采购、询价、订单、到货与异常链路。"""

    request_specs = (
        ("PR-26001", "研发实验室常用溶剂补充", "HIGH", 4200, 12, (("PRD-ETHANOL-AR", 50, "L"), ("PRD-ACETONE-AR", 40, "L"))),
        ("PR-26002", "酸碱试剂库存补充", "NORMAL", 3600, 20, (("PRD-HCL-AR", 50, "KG"), ("PRD-NAOH-AR", 75, "KG"))),
        ("PR-26003", "氧化剂安全库存建立", "URGENT", 2800, 28, (("PRD-H2O2-AR", 50, "KG"),)),
    )
    requests: list[tuple[PurchaseRequest, list[PurchaseRequestItem]]] = []
    for index, (request_no, purpose, priority, budget, day_offset, item_specs) in enumerate(request_specs):
        request = ensure(
            db,
            PurchaseRequest,
            {"request_no": request_no},
            {
                "applicant_id": users["BuyerUser"].id,
                "department_id": departments["PROCUREMENT"].id,
                "purpose": purpose,
                "priority": priority,
                "budget_amount": clean_decimal(budget),
                "currency_code": "CNY",
                "expected_date": TODAY + timedelta(days=day_offset),
                "status": "APPROVED" if index < 2 else "SUBMITTED",
                "submitted_at": NOW - timedelta(days=5 - index),
                "approved_at": NOW - timedelta(days=3 - index) if index < 2 else None,
            },
            counts,
        )
        items: list[PurchaseRequestItem] = []
        for line_no, (product_code, quantity, unit_code) in enumerate(item_specs, start=1):
            product = products[product_code]
            items.append(
                ensure(
                    db,
                    PurchaseRequestItem,
                    {"request_id": request.id, "line_no": line_no},
                    {
                        "product_id": product.id,
                        "requested_name": product.product_name,
                        "technical_requirements": "符合采购规格并提供 COA",
                        "quantity": clean_decimal(quantity),
                        "unit_id": units[unit_code].id,
                        "budget_price": clean_decimal(80 if unit_code == "L" else 18),
                        "expected_date": TODAY + timedelta(days=12 + index * 4),
                        "fulfilled_quantity": clean_decimal(quantity if index == 0 else 0),
                        "status": "FULFILLED" if index == 0 else "OPEN",
                    },
                    counts,
                )
            )
        requests.append((request, items))

    # 迁移 053 要求未标记历史重复的采购订单一对一对应独立比价单，因此三张订单各自关联独立 RFQ/QC。
    rfq_specs = (
        ("RFQ-26001", requests[0][0], [requests[0][1][0]], ("SUP-26001", "SUP-26002", "SUP-26004")),
        ("RFQ-26002", requests[1][0], requests[1][1], ("SUP-26001", "SUP-26003", "SUP-26004")),
        ("RFQ-26003", requests[0][0], [requests[0][1][1]], ("SUP-26001", "SUP-26002", "SUP-26004")),
    )
    quote_context: list[tuple[RFQ, dict[str, SupplierQuote], dict[tuple[str, str], SupplierQuoteItem], QuoteComparison]] = []
    for rfq_no, request, request_items, invited_codes in rfq_specs:
        rfq = ensure(
            db,
            RFQ,
            {"rfq_no": rfq_no},
            {
                "source_request_id": request.id,
                "requester_id": users["BuyerUser"].id,
                "quote_deadline": NOW + timedelta(days=4),
                "requested_delivery_date": TODAY + timedelta(days=18),
                "delivery_requirements": "送货至主仓，随货提供 COA",
                "status": "SENT",
                "sent_at": NOW - timedelta(days=2),
            },
            counts,
        )
        rfq_items: list[RFQItem] = []
        for idx_item, request_item in enumerate(request_items, start=1):
            rfq_items.append(
                ensure(
                    db,
                    RFQItem,
                    {"rfq_id": rfq.id, "line_no": idx_item},
                    {
                        "source_request_item_id": request_item.id,
                        "product_id": request_item.product_id,
                        "requested_name": request_item.requested_name,
                        "specification": "分析纯",
                        "quantity": request_item.quantity,
                        "unit_id": request_item.unit_id,
                        "required_delivery_date": request_item.expected_date,
                        "technical_requirements": request_item.technical_requirements,
                    },
                    counts,
                )
            )
        quotes: dict[str, SupplierQuote] = {}
        quote_items: dict[tuple[str, str], SupplierQuoteItem] = {}
        for supplier_index, supplier_code in enumerate(invited_codes):
            supplier = suppliers[supplier_code]
            ensure(
                db,
                RFQSupplier,
                {"rfq_id": rfq.id, "supplier_id": supplier.id},
                {
                    "response_status": "QUOTED",
                    "response_at": NOW - timedelta(days=1),
                    "invitation_channel": "EMAIL",
                },
                counts,
            )
            quote = ensure(
                db,
                SupplierQuote,
                {"quote_no": f"Q-{rfq_no[-5:]}-{supplier_index + 1:02d}"},
                {
                    "rfq_id": rfq.id,
                    "supplier_id": supplier.id,
                    "quote_version": 1,
                    "quote_date": TODAY - timedelta(days=1),
                    "valid_until": TODAY + timedelta(days=14),
                    "currency_code": "CNY",
                    "status": "SUBMITTED",
                    "received_by": users["BuyerUser"].id,
                },
                counts,
            )
            quotes[supplier_code] = quote
            for rfq_item in rfq_items:
                product_code = next(code for code, product in products.items() if product.id == rfq_item.product_id)
                unit_code = next(code for code, unit in units.items() if unit.id == rfq_item.unit_id)
                base_price = Decimal("72") if unit_code == "L" else Decimal("16")
                unit_price = base_price + Decimal(str(supplier_index * 2))
                quote_items[(supplier_code, product_code)] = ensure(
                    db,
                    SupplierQuoteItem,
                    {"quote_id": quote.id, "rfq_item_id": rfq_item.id},
                    {
                        "supplier_product_id": supplier_products[(supplier_code, product_code)].id,
                        "supplier_model": supplier_products[(supplier_code, product_code)].supplier_model,
                        "quoted_quantity": rfq_item.quantity,
                        "unit_id": rfq_item.unit_id,
                        "unit_price": unit_price,
                        "tax_rate": clean_decimal(13),
                        "moq_quantity": clean_decimal(25),
                        "moq_unit_id": rfq_item.unit_id,
                        "lead_days": suppliers[supplier_code].default_lead_days,
                        "payment_terms": "月结 30 天",
                    },
                    counts,
                )
        selected_supplier = invited_codes[0] if rfq_no != "RFQ-26002" else "SUP-26003"
        comparison = ensure(
            db,
            QuoteComparison,
            {"comparison_no": f"QC-{rfq_no[-5:]}"},
            {
                "rfq_id": rfq.id,
                "created_by": users["BuyerUser"].id,
                "selected_quote_id": quotes[selected_supplier].id,
                "conclusion": "综合价格、交期和历史履约表现后选择报价。",
                "selection_reason": "满足交期且综合成本最低。",
                "status": "CONFIRMED",
                "confirmed_by": users["BuyerUser"].id,
                "confirmed_at": NOW - timedelta(hours=12),
            },
            counts,
        )
        for rfq_item in rfq_items:
            product_code = next(code for code, product in products.items() if product.id == rfq_item.product_id)
            for rank, supplier_code in enumerate(invited_codes, start=1):
                quote_item = quote_items[(supplier_code, product_code)]
                ensure(
                    db,
                    QuoteComparisonItem,
                    {"comparison_id": comparison.id, "quote_id": quote_item.quote_id, "rfq_item_id": rfq_item.id},
                    {
                        "supplier_id": suppliers[supplier_code].id,
                        "quoted_unit_price": quote_item.unit_price,
                        "total_amount": quote_item.unit_price * quote_item.quoted_quantity,
                        "moq_quantity": quote_item.moq_quantity,
                        "lead_days": quote_item.lead_days,
                        "payment_terms": quote_item.payment_terms,
                        "historical_score": clean_decimal(92 - rank * 4),
                        "composite_score": clean_decimal(96 - rank * 3),
                        "rank_no": rank,
                        "selection_flag": 1 if supplier_code == selected_supplier else 0,
                    },
                    counts,
                )
        quote_context.append((rfq, quotes, quote_items, comparison))

    orders: list[tuple[PurchaseOrder, PurchaseOrderItem, str]] = []
    order_specs = (
        ("PO-26001", quote_context[0], "SUP-26001", "PRD-ETHANOL-AR", 50, "L", "RECEIVED"),
        ("PO-26002", quote_context[2], "SUP-26001", "PRD-ACETONE-AR", 40, "L", "PARTIAL"),
        ("PO-26003", quote_context[1], "SUP-26003", "PRD-HCL-AR", 50, "KG", "IN_TRANSIT"),
    )
    for po_no, (rfq, quotes, quote_items, comparison), supplier_code, product_code, quantity, unit_code, delivery_status in order_specs:
        product = products[product_code]
        quote = quotes[supplier_code]
        quote_item = quote_items[(supplier_code, product_code)]
        order = ensure(
            db,
            PurchaseOrder,
            {"po_no": po_no},
            {
                "supplier_id": suppliers[supplier_code].id,
                "source_comparison_id": comparison.id,
                "source_quote_id": quote.id,
                "source_request_id": rfq.source_request_id,
                "department_id": departments["PROCUREMENT"].id,
                "buyer_id": users["BuyerUser"].id,
                "order_amount": quote_item.unit_price * clean_decimal(quantity),
                "currency_code": "CNY",
                "delivery_address": "研发园区 A 区主仓",
                "order_date": TODAY - timedelta(days=10),
                "expected_arrival_date": TODAY - timedelta(days=3) if delivery_status != "IN_TRANSIT" else TODAY - timedelta(days=1),
                "status": (
                    "COMPLETED"
                    if delivery_status == "RECEIVED"
                    else "PARTIAL"
                    if delivery_status == "PARTIAL"
                    else "ORDERED"
                ),
                "supplier_confirmed_at": NOW - timedelta(days=8),
                "approved_at": NOW - timedelta(days=9),
            },
            counts,
        )
        order_item = ensure(
            db,
            PurchaseOrderItem,
            {"po_id": order.id, "line_no": 1},
            {
                "product_id": product.id,
                "supplier_product_id": supplier_products[(supplier_code, product_code)].id,
                "source_quote_item_id": quote_item.id,
                "product_name_snapshot": product.product_name,
                "supplier_model_snapshot": quote_item.supplier_model,
                "order_quantity": clean_decimal(quantity),
                "unit_id": units[unit_code].id,
                "unit_price": quote_item.unit_price,
                "tax_rate": clean_decimal(13),
                "planned_arrival_date": order.expected_arrival_date,
                "received_quantity": clean_decimal(
                    quantity
                    if delivery_status == "RECEIVED"
                    else quantity * Decimal("0.8")
                    if delivery_status == "PARTIAL"
                    else 0
                ),
                "status": "COMPLETED" if delivery_status == "RECEIVED" else "OPEN",
            },
            counts,
        )
        ensure(
            db,
            PurchaseOrderEvent,
            {"po_id": order.id, "event_type": "ORDERED"},
            {
                "event_time": NOW - timedelta(days=9),
                "operator_id": users["BuyerUser"].id,
                "from_status": "APPROVED",
                "to_status": "ORDERED",
                "event_note": "订单已正式下单",
            },
            counts,
        )
        orders.append((order, order_item, delivery_status))

    delivery_specs = (("DLV-26001", orders[0], "FULL", 0), ("DLV-26002", orders[1], "SHORT", 8), ("DLV-26003", orders[2], "OVERDUE", 0))
    deliveries: list[tuple[Delivery, DeliveryItem, str]] = []
    for delivery_no, (order, order_item, _delivery_status), scenario, short_quantity in delivery_specs:
        actual_quantity = (
            order_item.order_quantity
            if scenario == "FULL"
            else order_item.order_quantity - clean_decimal(short_quantity)
            if scenario == "SHORT"
            else Decimal("0.000000")
        )
        delivery = ensure(
            db,
            Delivery,
            {"delivery_no": delivery_no},
            {
                "po_id": order.id,
                "supplier_id": order.supplier_id,
                "shipment_date": TODAY - timedelta(days=7),
                "expected_arrival_date": order.expected_arrival_date,
                "actual_arrival_date": TODAY - timedelta(days=2) if scenario != "OVERDUE" else None,
                "logistics_company": "华东化工物流",
                "tracking_no": f"YT{delivery_no[-5:]}",
                "status": "ACCEPTED" if scenario == "FULL" else "RECEIVED" if scenario == "SHORT" else "IN_TRANSIT",
                "received_by": users["WarehouseUser"].id if scenario != "OVERDUE" else None,
                "received_at": NOW - timedelta(days=2) if scenario != "OVERDUE" else None,
            },
            counts,
        )
        delivery_item = ensure(
            db,
            DeliveryItem,
            {"delivery_id": delivery.id, "line_no": 1},
            {
                "po_item_id": order_item.id,
                "product_id": order_item.product_id,
                "batch_no": f"B{TODAY:%y%m}{delivery_no[-3:]}",
                "package_spec": "25L/桶" if order_item.unit_id == units["L"].id else "25kg/桶",
                "planned_quantity": order_item.order_quantity,
                "actual_quantity": actual_quantity,
                "short_quantity": clean_decimal(short_quantity),
                "unit_id": order_item.unit_id,
                "production_date": TODAY - timedelta(days=40),
                # 短交样本批次设在今日到期，既模拟效期预警也保证分页边界测试有基础样本。
                "expiry_date": TODAY if scenario == "SHORT" else TODAY + timedelta(days=320),
                "document_complete": 1 if scenario == "FULL" else 0,
                "note": None,
            },
            counts,
        )
        deliveries.append((delivery, delivery_item, scenario))
        if scenario != "OVERDUE":
            result = "PASSED" if scenario == "FULL" else "PARTIAL"
            ensure(
                db,
                QualityAcceptance,
                {"acceptance_no": f"QA-{delivery_no[-5:]}"},
                {
                    "delivery_id": delivery.id,
                    "inspector_id": users["QualityInspector"].id,
                    "result": result,
                    "inspection_time": NOW - timedelta(days=1),
                    "test_result": {"appearance": "符合要求", "identity": "合格"},
                    "certificate_complete": 1 if scenario == "FULL" else 0,
                    "conclusion": "抽检结果符合采购要求。" if scenario == "FULL" else "数量短交，待供应商补发。",
                },
                counts,
            )
            batch = ensure(
                db,
                InventoryBatch,
                {"product_id": order_item.product_id, "batch_no": delivery_item.batch_no, "source_delivery_id": delivery.id},
                {
                    "supplier_id": order.supplier_id,
                    "production_date": delivery_item.production_date,
                    "expiry_date": delivery_item.expiry_date,
                    "status": "ACTIVE",
                },
                counts,
            )
            ensure(
                db,
                InventoryBalance,
                {
                    "warehouse_id": warehouse.id,
                    "location_id": location.id,
                    "product_id": order_item.product_id,
                    "batch_id": batch.id,
                    "unit_id": order_item.unit_id,
                },
                {"quantity": actual_quantity, "locked_quantity": Decimal("0.000000"), "status": "AVAILABLE"},
                counts,
            )
            ensure(
                db,
                InventoryTransaction,
                {"transaction_no": f"IN-{delivery_no[-5:]}"},
                {
                    "transaction_type": "INBOUND",
                    "warehouse_id": warehouse.id,
                    "location_id": location.id,
                    "product_id": order_item.product_id,
                    "batch_id": batch.id,
                    "unit_id": order_item.unit_id,
                    "quantity": actual_quantity,
                    "delivery_item_id": delivery_item.id,
                    "source_type": "DELIVERY",
                    "source_id": delivery.id,
                    "operator_id": users["WarehouseUser"].id,
                    "note": None,
                },
                counts,
            )

    exception_specs = (
        ("EX-26001", "SHORT_DELIVERY", deliveries[1], "HIGH", "到货数量少于订单数量。", "PROCESSING"),
        ("EX-26002", "DOCUMENT_MISSING", deliveries[1], "MEDIUM", "到货资料未完整提供。", "OPEN"),
        ("EX-26003", "OVERDUE", deliveries[2], "HIGH", "采购订单超过计划到货日期仍未收货。", "OPEN"),
        ("EX-26004", "QUALITY", deliveries[0], "CRITICAL", "质量验收需要复核检测结果。", "CLOSED"),
    )
    for exception_no, exception_type, (delivery, delivery_item, _), severity, description, status in exception_specs:
        exception = ensure(
            db,
            OperationException,
            {"exception_no": exception_no},
            {
                "exception_type": exception_type,
                "source_type": "DELIVERY",
                "source_id": delivery.id,
                "po_id": delivery.po_id,
                "delivery_id": delivery.id,
                "delivery_item_id": delivery_item.id,
                "responsible_department_id": departments["QUALITY"].id if exception_type == "QUALITY" else departments["WAREHOUSE"].id,
                "owner_id": users["QualityInspector"].id if exception_type == "QUALITY" else users["WarehouseUser"].id,
                "severity": severity,
                "description": description,
                "status": status,
                "due_at": NOW + timedelta(days=2),
                "closed_by": users["QualityInspector"].id if status == "CLOSED" else None,
                "closed_at": NOW - timedelta(days=1) if status == "CLOSED" else None,
                "closing_note": "已完成复核并归档。" if status == "CLOSED" else None,
            },
            counts,
        )
        task = ensure(
            db,
            OperationTask,
            {"exception_id": exception.id, "title": "异常跟进"},
            {
                "assignee_id": exception.owner_id,
                "priority": "HIGH" if severity in ("HIGH", "CRITICAL") else "NORMAL",
                "due_at": exception.due_at,
                "status": "COMPLETED" if status == "CLOSED" else "PROCESSING" if status == "PROCESSING" else "OPEN",
                "completed_at": exception.closed_at,
                "completion_note": "复核完成。" if status == "CLOSED" else None,
            },
            counts,
        )
        ensure(
            db,
            OperationTaskComment,
            {"task_id": task.id, "commenter_id": users["BuyerUser"].id},
            {"content": "已联系相关人员跟进处理。"},
            counts,
        )
        ensure(
            db,
            Notification,
            {"recipient_id": exception.owner_id, "related_type": "OPERATION_EXCEPTION", "related_id": exception.id},
            {
                "notification_type": "EXCEPTION",
                "title": f"异常待处理：{exception_type}",
                "content": description,
                "is_read": 1 if status == "CLOSED" else 0,
                "read_at": NOW if status == "CLOSED" else None,
            },
            counts,
        )


def _seed_approval_and_extra_warehouses(
    db: Session,
    users: dict[str, User],
    counts: Counter[str],
) -> tuple[Warehouse, WarehouseLocation]:
    """补充待审批采购申请节点及多仓库、周转库位。"""

    pr_submitted = db.scalar(select(PurchaseRequest).where(PurchaseRequest.request_no == "PR-26003"))
    if pr_submitted is not None:
        ensure(
            db,
            PurchaseRequestApproval,
            {"request_id": pr_submitted.id, "sequence_no": 1},
            {
                "node_code": "PROCUREMENT_MANAGER",
                "node_name": "采购负责人审批",
                "action": "PENDING",
            },
            counts,
        )

    warehouse_user = users["WarehouseUser"]
    reserve = ensure(
        db,
        Warehouse,
        {"warehouse_code": "WH-SOLVENT-RESERVE"},
        {
            "warehouse_name": "易燃液体周转仓",
            "region": "华东园区",
            "address": "研发园区 B 区周转库",
            "manager_id": warehouse_user.id,
            "status": "ACTIVE",
            "note": "与主仓同类物料分区周转",
        },
        counts,
    )
    reserve_location = ensure(
        db,
        WarehouseLocation,
        {"warehouse_id": reserve.id, "location_code": "R-01-01"},
        {"location_name": "周转区 R 排 01 位", "status": "ACTIVE"},
        counts,
    )
    ensure(
        db,
        Warehouse,
        {"warehouse_code": "WH-CORROSIVE"},
        {"warehouse_name": "腐蚀品仓", "region": "华东园区", "manager_id": warehouse_user.id, "status": "ACTIVE"},
        counts,
    )
    ensure(
        db,
        Warehouse,
        {"warehouse_code": "WH-OXIDIZER"},
        {"warehouse_name": "氧化剂仓", "region": "华东园区", "manager_id": warehouse_user.id, "status": "ACTIVE"},
        counts,
    )
    return reserve, reserve_location


def _seed_inventory_and_replenish_workflows(
    db: Session,
    users: dict[str, User],
    departments: dict[str, Department],
    main_warehouse: Warehouse,
    main_location: WarehouseLocation,
    reserve_warehouse: Warehouse,
    reserve_location: WarehouseLocation,
    counts: Counter[str],
) -> None:
    """幂等写入成本层、研发领用、调拨、盘点及短交补货/质量退货记录。"""

    buyer = users["BuyerUser"]
    warehouse_user = users["WarehouseUser"]
    proc_manager = users["ProcManager"]
    rd = departments["R_AND_D"]

    inbounds = db.scalars(
        select(InventoryTransaction)
        .where(InventoryTransaction.transaction_type == "INBOUND")
        .order_by(InventoryTransaction.id)
    ).all()
    for tx in inbounds:
        po_item = (
            db.scalar(
                select(PurchaseOrderItem)
                .join(DeliveryItem, DeliveryItem.po_item_id == PurchaseOrderItem.id)
                .where(DeliveryItem.id == tx.delivery_item_id)
            )
            if tx.delivery_item_id is not None
            else db.scalar(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.product_id == tx.product_id)
                .order_by(PurchaseOrderItem.id)
            )
        )
        if po_item is None:
            continue
        ensure(
            db,
            InventoryCostLayer,
            {"source_transaction_id": tx.id},
            {
                "warehouse_id": tx.warehouse_id,
                "location_id": tx.location_id,
                "product_id": tx.product_id,
                "batch_id": tx.batch_id,
                "unit_id": tx.unit_id,
                "unit_cost": po_item.unit_price,
                "currency_code": "CNY",
                "original_quantity": tx.quantity,
                "remaining_quantity": tx.quantity,
            },
            counts,
        )

    balance = db.scalar(
        select(InventoryBalance)
        .join(
            InventoryTransaction,
            (InventoryTransaction.product_id == InventoryBalance.product_id)
            & (InventoryTransaction.batch_id == InventoryBalance.batch_id),
        )
        .where(InventoryTransaction.transaction_type == "INBOUND")
        .order_by(InventoryBalance.id)
    )
    if balance is None:
        raise RuntimeError("缺少入库库存余额，无法构造领用与调拨样本")
    layer = db.scalar(
        select(InventoryCostLayer)
        .where(
            InventoryCostLayer.batch_id == balance.batch_id,
            InventoryCostLayer.warehouse_id == balance.warehouse_id,
        )
        .order_by(InventoryCostLayer.id)
    )
    if layer is None:
        raise RuntimeError("缺少库存成本层，无法构造领用与调拨样本")

    if db.scalar(select(InventoryIssueRequest).where(InventoryIssueRequest.issue_no == "ISS-LAB-26001")) is None:
        qty_issue = Decimal("5.000000")
        issue = InventoryIssueRequest(
            issue_no="ISS-LAB-26001",
            applicant_id=buyer.id,
            department_id=rd.id,
            purpose="研发实验室溶剂领用：样品前处理",
            status="COMPLETED",
            approved_by=warehouse_user.id,
            approved_at=NOW - timedelta(days=1),
            completed_at=NOW,
        )
        db.add(issue)
        db.flush()
        db.add(
            InventoryIssueItem(
                issue_request_id=issue.id,
                line_no=1,
                product_id=balance.product_id,
                warehouse_id=balance.warehouse_id,
                location_id=balance.location_id,
                batch_id=balance.batch_id,
                unit_id=balance.unit_id,
                requested_quantity=qty_issue,
                issued_quantity=qty_issue,
                status="COMPLETED",
            )
        )
        out_tx = InventoryTransaction(
            transaction_no="OUT-LAB-26001",
            transaction_type="OUTBOUND",
            warehouse_id=balance.warehouse_id,
            location_id=balance.location_id,
            product_id=balance.product_id,
            batch_id=balance.batch_id,
            unit_id=balance.unit_id,
            quantity=qty_issue,
            source_type="ISSUE_REQUEST",
            source_id=issue.id,
            operator_id=warehouse_user.id,
            note="研发样品前处理领用",
        )
        db.add(out_tx)
        db.flush()
        db.add(
            InventoryCostAllocation(
                transaction_id=out_tx.id,
                cost_layer_id=layer.id,
                quantity=qty_issue,
                unit_cost=layer.unit_cost,
                total_cost=(qty_issue * layer.unit_cost).quantize(Decimal("0.000001")),
            )
        )
        layer.remaining_quantity -= qty_issue
        balance.quantity -= qty_issue
        counts["inventory_issue_requests"] += 1

    if db.scalar(select(InventoryTransferRequest).where(InventoryTransferRequest.transfer_no == "TRF-SOLVENT-26001")) is None:
        qty_transfer = Decimal("10.000000")
        transfer = InventoryTransferRequest(
            transfer_no="TRF-SOLVENT-26001",
            applicant_id=warehouse_user.id,
            purpose="实验室周转需求，调拨同类易燃液体仓",
            status="COMPLETED",
            approved_by=warehouse_user.id,
            approved_at=NOW - timedelta(hours=2),
            completed_at=NOW,
        )
        db.add(transfer)
        db.flush()
        db.add(
            InventoryTransferItem(
                transfer_request_id=transfer.id,
                line_no=1,
                product_id=balance.product_id,
                source_warehouse_id=main_warehouse.id,
                source_location_id=main_location.id,
                target_warehouse_id=reserve_warehouse.id,
                target_location_id=reserve_location.id,
                batch_id=balance.batch_id,
                unit_id=balance.unit_id,
                requested_quantity=qty_transfer,
                transferred_quantity=qty_transfer,
                status="COMPLETED",
            )
        )
        out_tx = InventoryTransaction(
            transaction_no="TRF-OUT-26001",
            transaction_type="TRANSFER_OUT",
            warehouse_id=main_warehouse.id,
            location_id=main_location.id,
            product_id=balance.product_id,
            batch_id=balance.batch_id,
            unit_id=balance.unit_id,
            quantity=qty_transfer,
            source_type="TRANSFER_REQUEST",
            source_id=transfer.id,
            operator_id=warehouse_user.id,
        )
        in_tx = InventoryTransaction(
            transaction_no="TRF-IN-26001",
            transaction_type="TRANSFER_IN",
            warehouse_id=reserve_warehouse.id,
            location_id=reserve_location.id,
            product_id=balance.product_id,
            batch_id=balance.batch_id,
            unit_id=balance.unit_id,
            quantity=qty_transfer,
            source_type="TRANSFER_REQUEST",
            source_id=transfer.id,
            operator_id=warehouse_user.id,
        )
        db.add_all([out_tx, in_tx])
        db.flush()
        db.add(
            InventoryCostAllocation(
                transaction_id=out_tx.id,
                cost_layer_id=layer.id,
                quantity=qty_transfer,
                unit_cost=layer.unit_cost,
                total_cost=(qty_transfer * layer.unit_cost).quantize(Decimal("0.000001")),
            )
        )
        layer.remaining_quantity -= qty_transfer
        balance.quantity -= qty_transfer
        db.add(
            InventoryBalance(
                warehouse_id=reserve_warehouse.id,
                location_id=reserve_location.id,
                product_id=balance.product_id,
                batch_id=balance.batch_id,
                unit_id=balance.unit_id,
                quantity=qty_transfer,
                locked_quantity=Decimal("0.000000"),
                status="AVAILABLE",
            )
        )
        db.add(
            InventoryCostLayer(
                source_transaction_id=in_tx.id,
                warehouse_id=reserve_warehouse.id,
                location_id=reserve_location.id,
                product_id=balance.product_id,
                batch_id=balance.batch_id,
                unit_id=balance.unit_id,
                unit_cost=layer.unit_cost,
                currency_code="CNY",
                original_quantity=qty_transfer,
                remaining_quantity=qty_transfer,
            )
        )
        counts["inventory_transfer_requests"] += 1

    stocktake = ensure(
        db,
        InventoryStocktakeRequest,
        {"stocktake_no": "STK-SOLVENT-26001"},
        {
            "applicant_id": warehouse_user.id,
            "warehouse_id": main_warehouse.id,
            "location_id": main_location.id,
            "purpose": "月度批次账实核对",
            "status": "COMPLETED",
            "approved_by": warehouse_user.id,
            "approved_at": NOW,
            "completed_at": NOW,
        },
        counts,
    )
    ensure(
        db,
        InventoryStocktakeItem,
        {"stocktake_request_id": stocktake.id, "line_no": 1},
        {
            "product_id": balance.product_id,
            "location_id": balance.location_id,
            "batch_id": balance.batch_id,
            "unit_id": balance.unit_id,
            "book_quantity": balance.quantity,
            "counted_quantity": balance.quantity,
            "difference_quantity": Decimal("0.000000"),
            "status": "COMPLETED",
            "note": "账实一致",
        },
        counts,
    )

    partial_po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == "PO-26002"))
    partial_delivery = db.scalar(select(Delivery).where(Delivery.po_id == partial_po.id))
    short_item = db.scalar(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == partial_po.id))
    replenish = ensure(
        db,
        ReplenishmentRequest,
        {"replenishment_no": "REP-SHORT-26001"},
        {
            "supplier_id": partial_po.supplier_id,
            "source_po_id": partial_po.id,
            "source_delivery_id": partial_delivery.id,
            "applicant_id": buyer.id,
            "reason": "到货短交 8 L，要求供应商按原单补足",
            "status": "APPROVED",
            "approved_by": proc_manager.id,
            "approved_at": NOW,
        },
        counts,
    )
    ensure(
        db,
        ReplenishmentItem,
        {"replenishment_request_id": replenish.id, "line_no": 1},
        {
            "product_id": short_item.product_id,
            "unit_id": short_item.unit_id,
            "requested_quantity": clean_decimal(8),
            "expected_date": TODAY + timedelta(days=5),
            "status": "OPEN",
        },
        counts,
    )

    short_balance = db.scalar(select(InventoryBalance).where(InventoryBalance.product_id == short_item.product_id))
    return_req = ensure(
        db,
        InventoryReturnRequest,
        {"return_no": "RET-QUALITY-26001"},
        {
            "supplier_id": partial_po.supplier_id,
            "po_id": partial_po.id,
            "delivery_id": partial_delivery.id,
            "applicant_id": warehouse_user.id,
            "reason": "待质量复核批次暂缓使用，申请退货评估",
            "status": "DRAFT",
        },
        counts,
    )
    ensure(
        db,
        InventoryReturnItem,
        {"return_request_id": return_req.id, "line_no": 1},
        {
            "product_id": short_item.product_id,
            "warehouse_id": short_balance.warehouse_id,
            "location_id": short_balance.location_id,
            "batch_id": short_balance.batch_id,
            "unit_id": short_balance.unit_id,
            "requested_quantity": clean_decimal(2),
            "returned_quantity": Decimal("0.000000"),
            "status": "OPEN",
        },
        counts,
    )


def _seed_second_dept_order_and_acceptance(
    db: Session,
    users: dict[str, User],
    departments: dict[str, Department],
    products: dict,
    suppliers: dict[str, Supplier],
    supplier_products: dict[tuple[str, str], SupplierProduct],
    units: dict,
    warehouse: Warehouse,
    location: WarehouseLocation,
    counts: Counter[str],
) -> PurchaseOrder:
    """补充质量部门（第二部门）已完成验收的采购订单，用于部门隔离与财务匹配测试。"""

    supplier = suppliers["SUP-26002"]
    product = products["PRD-ETHANOL-AR"]
    sup_product = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == supplier.id,
            SupplierProduct.product_id == product.id,
        )
    )
    qty = clean_decimal(20)
    unit_price = clean_decimal(74)
    amount = (qty * unit_price).quantize(Decimal("0.000001"))

    order = ensure(
        db,
        PurchaseOrder,
        {"po_no": "PO-CI-DEPT2-01"},
        {
            "supplier_id": supplier.id,
            "department_id": departments["QUALITY"].id,
            "buyer_id": users["QualityManager"].id,
            "order_amount": amount,
            "currency_code": "CNY",
            "delivery_address": "研发园区质量检测中心",
            "order_date": TODAY - timedelta(days=8),
            "expected_arrival_date": TODAY - timedelta(days=2),
            "status": "COMPLETED",
            "supplier_confirmed_at": NOW - timedelta(days=7),
            "approved_at": NOW - timedelta(days=7),
            "note": "CI 跨部门权限隔离与全链路样本订单",
        },
        counts,
    )
    po_item = ensure(
        db,
        PurchaseOrderItem,
        {"po_id": order.id, "line_no": 1},
        {
            "product_id": product.id,
            "supplier_product_id": sup_product.id if sup_product else None,
            "product_name_snapshot": product.product_name,
            "supplier_model_snapshot": sup_product.supplier_model if sup_product else product.model,
            "order_quantity": qty,
            "unit_id": units["L"].id,
            "unit_price": unit_price,
            "tax_rate": clean_decimal(13),
            "planned_arrival_date": order.expected_arrival_date,
            "received_quantity": qty,
            "status": "COMPLETED",
        },
        counts,
    )
    ensure(
        db,
        PurchaseOrderEvent,
        {"po_id": order.id, "event_type": "ORDERED"},
        {
            "event_time": NOW - timedelta(days=7),
            "operator_id": users["QualityManager"].id,
            "from_status": "APPROVED",
            "to_status": "ORDERED",
            "event_note": "质量部门样本订单已下单",
        },
        counts,
    )

    delivery = ensure(
        db,
        Delivery,
        {"delivery_no": "DLV-CI-DEPT2-01"},
        {
            "po_id": order.id,
            "supplier_id": supplier.id,
            "shipment_date": TODAY - timedelta(days=5),
            "expected_arrival_date": order.expected_arrival_date,
            "actual_arrival_date": TODAY - timedelta(days=2),
            "logistics_company": "华东化工物流",
            "tracking_no": "YTCI0002",
            "status": "ACCEPTED",
            "received_by": users["WarehouseUser"].id,
            "received_at": NOW - timedelta(days=2),
        },
        counts,
    )
    delivery_item = ensure(
        db,
        DeliveryItem,
        {"delivery_id": delivery.id, "line_no": 1},
        {
            "po_item_id": po_item.id,
            "product_id": product.id,
            "batch_no": f"BCI{TODAY:%y%m}02",
            "package_spec": "20L/桶",
            "planned_quantity": qty,
            "actual_quantity": qty,
            "short_quantity": Decimal("0.000000"),
            "unit_id": units["L"].id,
            "production_date": TODAY - timedelta(days=30),
            "expiry_date": TODAY + timedelta(days=330),
            "document_complete": 1,
        },
        counts,
    )
    ensure(
        db,
        QualityAcceptance,
        {"acceptance_no": "QA-CI-DEPT2-01"},
        {
            "delivery_id": delivery.id,
            "inspector_id": users["QualityInspector"].id,
            "result": "PASSED",
            "inspection_time": NOW - timedelta(days=1),
            "test_result": {"外观": "澄清透明", "纯度": "99.6%"},
            "certificate_complete": 1,
            "conclusion": "质量部门样本抽检合格。",
        },
        counts,
    )
    batch = ensure(
        db,
        InventoryBatch,
        {"product_id": product.id, "batch_no": delivery_item.batch_no, "source_delivery_id": delivery.id},
        {
            "supplier_id": supplier.id,
            "production_date": delivery_item.production_date,
            "expiry_date": delivery_item.expiry_date,
            "status": "ACTIVE",
        },
        counts,
    )
    ensure(
        db,
        InventoryBalance,
        {
            "warehouse_id": warehouse.id,
            "location_id": location.id,
            "product_id": product.id,
            "batch_id": batch.id,
            "unit_id": units["L"].id,
        },
        {"quantity": qty, "locked_quantity": Decimal("0.000000"), "status": "AVAILABLE"},
        counts,
    )
    ensure(
        db,
        InventoryTransaction,
        {"transaction_no": "IN-CI-DEPT2-01"},
        {
            "transaction_type": "INBOUND",
            "warehouse_id": warehouse.id,
            "location_id": location.id,
            "product_id": product.id,
            "batch_id": batch.id,
            "unit_id": units["L"].id,
            "quantity": qty,
            "delivery_item_id": delivery_item.id,
            "source_type": "DELIVERY",
            "source_id": delivery.id,
            "operator_id": users["WarehouseUser"].id,
        },
        counts,
    )
    return order


def _seed_quality_report_review(db: Session, users: dict[str, User], counts: Counter[str]) -> None:
    """为 QA-26001 写入质量检验报告文件与核对快照，覆盖报告权限与追溯测试。"""

    qa = db.scalar(select(QualityAcceptance).where(QualityAcceptance.acceptance_no == "QA-26001"))
    if qa is None:
        raise RuntimeError("缺少 QA-26001，无法构造质量报告复核样本")
    existing = db.scalar(
        select(QualityReportReviewRecord).where(QualityReportReviewRecord.acceptance_id == qa.id)
    )
    if existing is not None:
        return

    delivery_item = db.scalar(
        select(DeliveryItem).where(DeliveryItem.delivery_id == qa.delivery_id).order_by(DeliveryItem.line_no)
    )
    if delivery_item is None:
        raise RuntimeError("QA-26001 关联到货单缺少明细")
    inspector = users["QualityInspector"]
    reviewer = users["QualityManager"]

    report_file = file_service.upload_file(
        db,
        inspector,
        file_name="qa-26001-coa-report.pdf",
        mime_type="application/pdf",
        content=_MINIMAL_PDF,
        file_category="QUALITY_REPORT",
        access_level="INTERNAL",
    )
    qa.report_file_id = report_file.id
    if (
        db.scalar(
            select(SysFileAttachment).where(
                SysFileAttachment.resource_type == "QUALITY_ACCEPTANCE",
                SysFileAttachment.resource_id == qa.id,
                SysFileAttachment.file_id == report_file.id,
            )
        )
        is None
    ):
        db.add(
            SysFileAttachment(
                file_id=report_file.id,
                resource_type="QUALITY_ACCEPTANCE",
                resource_id=qa.id,
                created_by=inspector.id,
            )
        )
    review_model = QualityReportReview(
        acceptance_id=qa.id,
        delivery_item_id=delivery_item.id,
        product_name="无水乙醇",
        product_model="AR",
        report_product_name="无水乙醇",
        report_product_model="AR",
        product_status="MATCH",
        file_id=report_file.id,
        file_name=report_file.file_name,
        report_batch_no=delivery_item.batch_no,
        expected_batch_nos=[delivery_item.batch_no] if delivery_item.batch_no else [],
        batch_status="MATCH" if delivery_item.batch_no else "UNVERIFIED",
        checks=[
            QualityReportCheck(
                item_name="纯度",
                report_value="99.6%",
                recorded_value="99.5%",
                source_quote="Assay (GC): 99.6%",
                source_location="第1页",
                status="MATCH",
            )
        ],
        warnings=[],
        reviewed_at=datetime.now(),
    )
    record = QualityReportReviewRecord(
        acceptance_id=qa.id,
        delivery_item_id=delivery_item.id,
        file_id=report_file.id,
        standard_id=None,
        result_json=review_model.model_dump(mode="json"),
        status="CONFIRMED",
        reviewer_note="CI 样本报告核对与批次信息一致",
        created_by=inspector.id,
        reviewed_by=reviewer.id,
        reviewed_at=datetime.now(),
    )
    db.add(record)
    db.flush()
    review_model.review_id = record.id
    record.result_json = review_model.model_dump(mode="json")
    db.commit()
    counts["quality_report_reviews"] += 1


def _seed_doc_kb(db: Session, counts: Counter[str]) -> None:
    """为乙醇写入 MSDS 与 TDS 离线解析章节，供文档检索与回归测试使用。"""

    msds_content = "Flash point: 13 °C (closed cup); Boiling point: 78.37 °C; Density: 0.789 g/cm3 at 20 °C."
    tds_content = "Chemical Formula: C2H6O; Molecular Weight: 46.07; Appearance: Clear colorless liquid; Purity >= 99.5%."
    specs = (
        (
            "msds",
            "doc-kb/64-17-5/msds-ci.pdf",
            "乙醇安全技术说明书 (MSDS)",
            9,
            "section-9",
            "SECTION 9: Physical and chemical properties",
            msds_content,
        ),
        (
            "tds",
            "doc-kb/64-17-5/tds-ci.pdf",
            "乙醇技术数据表 (TDS)",
            1,
            "section-1",
            "第 1 页",
            tds_content,
        ),
    )
    for doc_type, object_key, title, section_no, section_key, section_title, content in specs:
        doc = ensure(
            db,
            AiDocument,
            {"cas_no": "64-17-5", "doc_type": doc_type, "object_key": object_key},
            {
                "title": title,
                "name_zh": "乙醇",
                "source_bucket": "ci-seed",
                "source_url": None,
                "parse_status": "PARSED",
                "section_count": 1,
                "char_count": len(content),
                "meta_json": {"source": "ci_seed"},
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
            counts,
        )
        ensure(
            db,
            AiDocumentSection,
            {"document_id": doc.id, "section_key": section_key},
            {
                "cas_no": "64-17-5",
                "doc_type": doc_type,
                "section_no": section_no,
                "title": section_title,
                "content": content,
                "char_count": len(content),
            },
            counts,
        )


def _seed_finance_workflows(db: Session, users: dict[str, User], counts: Counter[str]) -> None:
    """构造成对财务对账与发票匹配状态。

    1. PO-26001：确认对账单但保留未开票额度，满足发票自动提取与入账测试；
    2. PO-CI-DEPT2-01：完成对账单确认、发票录入、行匹配版本绑定与提交核验，覆盖完整财务链路。
    """

    finance_user = users["FinanceClerk"]
    finance_manager = users["FinanceManager"]

    po_26001 = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == "PO-26001"))
    if po_26001 is None:
        raise RuntimeError("缺少 PO-26001，无法构造财务对账单")
    dlv_26001 = db.scalar(select(Delivery).where(Delivery.po_id == po_26001.id))
    if dlv_26001 is not None and dlv_26001.status != "ACCEPTED":
        dlv_26001.status = "ACCEPTED"
        db.commit()
    if db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == po_26001.id)) is None:
        rec_1 = finance_service.create_reconciliation(db, finance_user, po_26001.id, "CI 样本对账单（待开票）")
        finance_service.confirm_reconciliation(db, finance_manager, rec_1.id, "对账金额核对一致，待供应商开票")
        counts["finance_reconciliations"] += 1

    po_dept2 = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == "PO-CI-DEPT2-01"))
    if po_dept2 is None:
        raise RuntimeError("缺少 PO-CI-DEPT2-01，无法构造财务发票匹配样本")
    if db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == po_dept2.id)) is None:
        rec_2 = finance_service.create_reconciliation(db, finance_user, po_dept2.id, "CI 样本对账单（含已提交发票）")
        rec_2 = finance_service.confirm_reconciliation(db, finance_manager, rec_2.id, "对账金额核对一致")
        lines, _ = invoice_matches.line_summary(db, rec_2)
        if not lines:
            raise RuntimeError("PO-CI-DEPT2-01 对账单缺少对账明细")
        excl_total = sum((Decimal(row["amount_excl_tax"]) for row in lines), Decimal("0.00"))
        tax_total = sum((Decimal(row["tax_amount"]) for row in lines), Decimal("0.00"))
        incl_total = sum((Decimal(row["amount_incl_tax"]) for row in lines), Decimal("0.00"))
        invoice = finance_service.create_invoice(
            db,
            finance_user,
            InvoiceCreate(
                reconciliation_id=rec_2.id,
                invoice_code="031002600111",
                invoice_number="FPCI20260002",
                invoice_date=TODAY - timedelta(days=1),
                amount_excl_tax=excl_total,
                tax_amount=tax_total,
                amount_incl_tax=incl_total,
                note="CI 全链路样本发票",
            ),
        )
        invoice_matches.save_match(
            db,
            finance_user,
            invoice.id,
            InvoiceMatchSave(
                reconciliation_version=rec_2.items_version,
                allocations=[
                    InvoiceAllocation(
                        reconciliation_item_id=row["reconciliation_item_id"],
                        amount_excl_tax=Decimal(row["amount_excl_tax"]),
                        tax_amount=Decimal(row["tax_amount"]),
                    )
                    for row in lines
                ],
                note="按当前对账版本全额分配",
            ),
        )
        finance_service.submit_invoice(db, finance_user, invoice.id)
        counts["finance_reconciliations"] += 1
        counts["finance_invoices"] += 1


def _seed_warehouse_grants(db: Session, users: dict[str, User], counts: Counter[str]) -> None:
    """按仓库负责人关系幂等补齐仓库数据范围与显式授权，与迁移 066 保持一致。"""

    warehouse_user = users["WarehouseUser"]
    for warehouse in db.scalars(select(Warehouse)).all():
        if warehouse.manager_id is None:
            warehouse.manager_id = warehouse_user.id

    for user in db.scalars(select(User)).all():
        roles = set(get_user_role_codes(db, user.id))
        if "SYS_ADMIN" in roles or roles == {"SUPPLIER_PORTAL"}:
            continue
        if db.get(UserWarehouseScope, user.id) is None:
            db.add(UserWarehouseScope(user_id=user.id))
            counts["sys_user_warehouse_scopes"] += 1

    db.flush()
    for warehouse in db.scalars(select(Warehouse).where(Warehouse.status == "ACTIVE")).all():
        if warehouse.manager_id is None:
            continue
        if db.get(UserWarehouseScope, warehouse.manager_id) is None:
            db.add(UserWarehouseScope(user_id=warehouse.manager_id))
            counts["sys_user_warehouse_scopes"] += 1
        if db.get(UserWarehouseGrant, (warehouse.manager_id, warehouse.id)) is None:
            db.add(UserWarehouseGrant(user_id=warehouse.manager_id, warehouse_id=warehouse.id))
            counts["sys_user_warehouse_grants"] += 1


def seed_all(*, allow_isolated_test_db: bool = False) -> Counter[str]:
    """按依赖顺序幂等装载完整 CI 样本数据集。"""

    _ensure_safe_target(allow_isolated_test_db)
    counts: Counter[str] = Counter()
    db = SessionLocal()
    try:
        departments, users = _load_org_context(db)
        chemical_map = _seed_offline_chemicals(db, counts)
        units = load_units(db, counts)
        products, suppliers, supplier_products, warehouse, location = load_master_data(db, chemical_map, units, counts)
        _seed_procurement_chain(db, products, suppliers, supplier_products, units, departments, users, warehouse, location, counts)
        reserve, reserve_location = _seed_approval_and_extra_warehouses(db, users, counts)
        _seed_warehouse_grants(db, users, counts)
        _seed_second_dept_order_and_acceptance(
            db,
            users,
            departments,
            products,
            suppliers,
            supplier_products,
            units,
            warehouse,
            location,
            counts,
        )
        _seed_inventory_and_replenish_workflows(
            db,
            users,
            departments,
            warehouse,
            location,
            reserve,
            reserve_location,
            counts,
        )
        _seed_doc_kb(db, counts)
        db.commit()

        # 文件上传、报告复核与财务状态机内部提交独立事务。
        _seed_quality_report_review(db, users, counts)
        _seed_finance_workflows(db, users, counts)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return counts


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="为 CI 或隔离测试库装载离线完整业务样本数据")
    parser.add_argument(
        "--allow-isolated-test-db",
        action="store_true",
        help="允许写入隔离测试库；未设置 CI=true 时防止误写默认开发库",
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口：写入并打印本次新增记录统计。"""

    args = parse_args()
    counts = seed_all(allow_isolated_test_db=args.allow_isolated_test_db)
    print("ci_test_data_ready=true")
    for table_name, created_count in sorted(counts.items()):
        print(f"created_{table_name}={created_count}")


if __name__ == "__main__":
    main()
