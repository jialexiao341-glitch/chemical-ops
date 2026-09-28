"""Add varied, linked synthetic business cases to the local development database.

Chemical identities were imported separately from PubChem. Every procurement,
warehouse, finance and task record here is a plausible simulation, not evidence
of a real purchase, invoice, payment, inspection or stock movement.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.chemicals.model import Chemical
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.inventory.model import (InventoryBalance, InventoryBatch, InventoryIssueItem, InventoryIssueRequest,
    InventoryStocktakeItem, InventoryStocktakeRequest, InventoryTransaction, InventoryTransferItem,
    InventoryTransferRequest, Warehouse, WarehouseLocation)
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest
from app.modules.notifications.model import Notification
from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment
from app.modules.products.model import Product
from app.modules.products.category_model import ProductCategory
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from app.modules.purchase_requests.model import PurchaseRequest, PurchaseRequestApproval, PurchaseRequestItem
from app.modules.purchase_requests.model import Unit
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.replenishments.model import ReplenishmentItem, ReplenishmentRequest
from app.modules.rfqs.model import RFQ, RFQItem, RFQSupplier, QuoteComparison, QuoteComparisonItem, SupplierQuote, SupplierQuoteItem
from app.modules.suppliers.product_model import SupplierProduct
from app.modules.suppliers.model import Supplier
from app.modules.system.model import Department, User
from rebuild_curated_development_data import verify
from curated_record_copy import acceptance_copy, batch_no, business_no


TODAY = date.today()
NOW = datetime.now(timezone.utc).replace(tzinfo=None)
D = lambda value: Decimal(str(value))

# Distinct operational backgrounds, amounts, quantities, stages and suppliers.
# case, product, quantity, unit price, background, stage, supplier option
CASES = (
    (1, "PRD-METHANOL-AR", 32, 58, "色谱分析项目启动，补充甲醇流动相储备", "SETTLED", 0),
    (2, "PRD-HCL-AR", 75, 19, "水处理班组月度酸碱试剂补库", "SETTLED", 1),
    (3, "PRD-NAOH-AR", 125, 14, "中和工序季度安全库存调整", "SETTLED", 2),
    (4, "PRD-ACETONE-AR", 60, 66, "设备检修后的表面清洁物料补充", "SETTLED", 1),
    (5, "PRD-ETHANOL-AR", 80, 72, "质量实验室留样前处理用量增加", "SETTLED", 2),
    (6, "PRD-H2O2-AR", 50, 32, "环境监测专项检测试剂储备", "SETTLED", 0),
    (7, "PRD-SULFURIC-AR", 100, 26, "循环水系统维护后的酸试剂补给", "RECEIVED", 1),
    (8, "PRD-ACETIC-AR", 40, 28, "研发小试缓冲液配制物料补库", "RECEIVED", 0),
    (9, "PRD-METHANOL-AR", 45, 60, "分析方法验证批次增加，申请追加溶剂", "SHORT", 1),
    (10, "PRD-NAOH-AR", 90, 15, "生产线清洁窗口前补充碱性试剂", "DOCUMENT", 0),
    (11, "PRD-ACETONE-AR", 100, 65, "停机检修备件清洁所需物料预采购", "TRANSIT", 0),
    (12, "PRD-H2O2-AR", 75, 33, "秋季安全库存复核后补充氧化剂", "ORDERED", 1),
    (13, "PRD-ETHANOL-AR", 120, 73, "下一周期实验室共用溶剂年度框架询价", "RFQ", 1),
    (14, "PRD-HCL-AR", 50, 21, "新检验规程试运行前评估供应交期", "RFQ", 2),
    (15, "PRD-ACETIC-AR", 25, 30, "小试项目追加冰醋酸，待部门预算审批", "SUBMITTED", 1),
    (16, "PRD-SULFURIC-AR", 50, 27, "下季度仪器维护预计用量，待确认需求", "DRAFT", 0),
    (17, "PRD-METHANOL-AR", 20, 62, "验证项目备用采购方案，待技术规格确认", "DRAFT", 0),
    (18, "PRD-NAOH-AR", 150, 13, "集中采购计划，比较批量交付可行性", "RFQ", 1),
    (19, "PRD-TOLUENE-AR", 36, 79, "材料相容性试验新增甲苯消耗预测", "SETTLED", 0),
    (20, "PRD-ETHYLACETATE-AR", 64, 68, "分离纯化项目的乙酸乙酯周转补货", "RECEIVED", 1),
    (21, "PRD-ACETONITRILE-AR", 28, 116, "色谱验证批次增加，补充乙腈", "SETTLED", 0),
    (22, "PRD-TOLUENE-AR", 72, 77, "检修窗口前的溶剂储备计划", "SHORT", 1),
    (23, "PRD-ETHYLACETATE-AR", 48, 70, "研发中试项目转入下一阶段的预采购", "TRANSIT", 0),
    (24, "PRD-ACETONITRILE-AR", 56, 114, "实验室联合采购，比较交期与分批供货能力", "RFQ", 1),
    (25, "PRD-ETHYLACETATE-AR", 24, 72, "样品分析耗材补充，等待主管核准", "SUBMITTED", 0),
    (26, "PRD-TOLUENE-AR", 40, 82, "下一周期稳定性研究预估需求", "DRAFT", 1),
)


def add(db, counts, cls, **values):
    row = cls(**values)
    db.add(row)
    db.flush()
    counts[cls.__tablename__] += 1
    return row


def preflight(db):
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise RuntimeError("Only the local ChemicalOps development database may be changed")
    if db.scalar(select(PurchaseRequest.id).where(PurchaseRequest.request_no.in_(("SCN26-01-PR", "PR-2026-0001")))):
        return False
    if db.scalar(text("SELECT COUNT(*) FROM purchase_requests")) < 3 or db.scalar(text("SELECT COUNT(*) FROM md_products")) < 8:
        raise RuntimeError("Run the curated rebuild before the extension")
    return True


def main_seed(db, cases=CASES, *, add_master=True):
    counts = Counter()
    users = {x.username: x for x in db.scalars(select(User)).all()}
    departments = {x.department_code: x for x in db.scalars(select(Department)).all()}
    products = {x.product_code: x for x in db.scalars(select(Product)).all()}
    chemicals = {x.cas_no: x for x in db.scalars(select(Chemical)).all()}
    category = db.scalar(select(ProductCategory).where(ProductCategory.category_code == "SOLVENT"))
    litre = db.scalar(select(Unit).where(Unit.unit_code == "L"))
    suppliers = list(db.scalars(select(Supplier)).all())
    if add_master:
        suppliers.extend((
        add(db, counts, Supplier, supplier_code="SUP-2026-0005", supplier_name="华东试剂配送中心",
            country_code="CN", region="华东", cooperation_level="B", default_lead_days=6,
            status="ACTIVE", note="华东地区常规试剂配送，支持批次资料随货交付"),
        add(db, counts, Supplier, supplier_code="SUP-2026-0006", supplier_name="北方实验材料供应中心",
            country_code="CN", region="华北", cooperation_level="B", default_lead_days=8,
            status="ACTIVE", note="华北地区实验材料供货，按采购订单安排交期"),
        ))
    for code, name, cas, packaging in (() if not add_master else (
        ("PRD-TOLUENE-AR", "甲苯", "108-88-3", "20L/桶"),
        ("PRD-ETHYLACETATE-AR", "乙酸乙酯", "141-78-6", "20L/桶"),
        ("PRD-ACETONITRILE-AR", "乙腈", "75-05-8", "20L/桶"),
    )):
        if cas not in chemicals:
            raise RuntimeError(f"Verified chemical identity unavailable: {cas}")
        product = add(db, counts, Product, product_code=code, product_name=name,
            chemical_id=chemicals[cas].id, category_id=category.id, model="AR",
            purity_value=D("99.5"), purity_unit="%", packaging_spec=packaging,
            unit_id=litre.id, parameter_json={"sample_data": True, "certificate_required": True},
            version_no=1, status="ACTIVE")
        products[code] = product
        for option, supplier in enumerate((suppliers[0], suppliers[4], suppliers[5])):
            add(db, counts, SupplierProduct, supplier_id=supplier.id, product_id=product.id,
                supplier_model=f"AR-{option+1:02d}", supplied_purity=D("99.5"),
                moq_quantity=D(20), moq_unit_id=litre.id,
                standard_lead_days=supplier.default_lead_days,
                capacity_note="常备规格可按订单分批交付", status="ACTIVE",
                note="交期以订单确认为准，随货提供批次资料")
    supplier_products = {}
    for sp in db.scalars(select(SupplierProduct).where(SupplierProduct.status == "ACTIVE")).all():
        supplier_products.setdefault(sp.product_id, []).append(sp)
    buyer, receiver, inspector = (users[k] for k in ("buyer", "warehouse_receiver", "quality_inspector"))
    finance, manager = users["finance_clerk"], users["finance_manager"]

    old_submitted = db.scalar(select(PurchaseRequest).where(PurchaseRequest.request_no == "PR-26003"))
    if old_submitted and not db.scalar(select(PurchaseRequestApproval.id).where(PurchaseRequestApproval.request_id == old_submitted.id)):
        add(db, counts, PurchaseRequestApproval, request_id=old_submitted.id, sequence_no=1,
            node_code="PROCUREMENT_MANAGER", node_name="采购负责人审批", action="PENDING")
    first_delivery = db.scalar(select(Delivery).where(Delivery.delivery_no == "DLV-26001"))
    if first_delivery:
        first_delivery.status = "ACCEPTED"

    warehouses = {x.warehouse_code: x for x in db.scalars(select(Warehouse)).all()}
    locations = {x.warehouse_id: x for x in db.scalars(select(WarehouseLocation)).all()}
    for code, label in (("WH-CORROSIVE", "腐蚀品区 C 排 01 位"), ("WH-OXIDIZER", "氧化剂区 O 排 01 位")):
        wh = warehouses[code]
        if wh.id not in locations:
            locations[wh.id] = add(db, counts, WarehouseLocation, warehouse_id=wh.id,
                location_code="A-01-01", location_name=label, status="ACTIVE")

    balances = []
    for number, code, qty, price, background, stage, supplier_option in cases:
        age = number % 25
        product = products[code]
        sp = supplier_products[product.id][supplier_option % len(supplier_products[product.id])]
        supplier_id = sp.supplier_id
        priority = "HIGH" if number in (3, 6, 9, 10, 12) else "NORMAL"
        submitted = stage not in ("DRAFT",)
        approved = stage not in ("DRAFT", "SUBMITTED")
        request = add(db, counts, PurchaseRequest, request_no=business_no(number, "PR"), applicant_id=buyer.id,
            department_id=departments["PROCUREMENT"].id, purpose=background,
            priority=priority, budget_amount=D(qty * price * 1.08), currency_code="CNY",
            expected_date=TODAY + timedelta(days=number % 13 + 5),
            status="APPROVED" if approved else "SUBMITTED" if submitted else "DRAFT",
            submitted_at=NOW - timedelta(days=age + 17) if submitted else None,
            approved_at=NOW - timedelta(days=age + 15) if approved else None)
        pr_item = add(db, counts, PurchaseRequestItem, request_id=request.id, line_no=1,
            product_id=product.id, requested_name=product.product_name,
            technical_requirements="按现行采购规格供货，随货提供批次合格证明；用途：" + background,
            quantity=D(qty), unit_id=product.unit_id, budget_price=D(price * 1.08),
            expected_date=request.expected_date, fulfilled_quantity=D(0), status="OPEN")
        if submitted:
            add(db, counts, PurchaseRequestApproval, request_id=request.id, sequence_no=1,
                node_code="PROCUREMENT_MANAGER", node_name="采购负责人审批",
                approver_id=manager.id if approved else None, action="APPROVED" if approved else "PENDING",
                opinion="需求与预算已核对" if approved else None, acted_at=request.approved_at)
        if not approved:
            continue

        rfq = add(db, counts, RFQ, rfq_no=business_no(number, "RFQ"), source_request_id=request.id,
            requester_id=buyer.id, quote_deadline=NOW + timedelta(days=4) if stage == "RFQ" else NOW - timedelta(days=age + 11),
            requested_delivery_date=request.expected_date,
            delivery_requirements="按批次分装，随货提供产品合格证明；" + background,
            status="SENT" if stage == "RFQ" else "CLOSED", sent_at=NOW - timedelta(days=age + 14),
            closed_at=NOW - timedelta(days=age + 12) if stage != "RFQ" else None)
        rfq_item = add(db, counts, RFQItem, rfq_id=rfq.id, line_no=1,
            source_request_item_id=pr_item.id, product_id=product.id,
            requested_name=product.product_name, specification=product.model,
            quantity=D(qty), unit_id=product.unit_id, required_delivery_date=request.expected_date,
            technical_requirements=pr_item.technical_requirements)
        quote_options = supplier_products[product.id][:max(2, supplier_option + 1)]
        selected_quote = selected_quote_item = comparison = None
        for option_index, option in enumerate(quote_options):
            add(db, counts, RFQSupplier, rfq_id=rfq.id, supplier_id=option.supplier_id,
                response_status="QUOTED", response_at=NOW - timedelta(days=age + 13),
                invitation_channel="EMAIL", note="供应商已按询价要求反馈报价及交期")
            quoted_price = D(price + (2 if option.supplier_id != supplier_id else 0))
            quote = add(db, counts, SupplierQuote, quote_no=f"{business_no(number, 'QUO')}-{option_index + 1}",
                rfq_id=rfq.id, supplier_id=option.supplier_id, quote_version=1,
                quote_date=TODAY - timedelta(days=age + 13), valid_until=TODAY + timedelta(days=12),
                currency_code="CNY", status="SUBMITTED", received_by=buyer.id,
                note="报价按本次询价数量及约定交期填报，有效期内待采购确认")
            quote_item = add(db, counts, SupplierQuoteItem, quote_id=quote.id,
                rfq_item_id=rfq_item.id, supplier_product_id=option.id,
                supplier_model=option.supplier_model, quoted_quantity=D(qty), unit_id=product.unit_id,
                unit_price=quoted_price, tax_rate=D(13), moq_quantity=option.moq_quantity,
                moq_unit_id=product.unit_id, lead_days=option.standard_lead_days,
                payment_terms="验收后月结", note=background)
            if option.supplier_id == supplier_id:
                selected_quote, selected_quote_item = quote, quote_item
        if stage == "RFQ":
            continue
        comparison = add(db, counts, QuoteComparison, comparison_no=business_no(number, "CMP"),
            rfq_id=rfq.id, created_by=buyer.id, selected_quote_id=selected_quote.id,
            conclusion="综合报价和供应交期，选用符合本次任务需求的供应商。",
            selection_reason=background, status="CONFIRMED", confirmed_by=manager.id,
            confirmed_at=NOW - timedelta(days=age + 12))
        for option_index, option in enumerate(quote_options):
            quote = db.scalar(select(SupplierQuote).where(SupplierQuote.rfq_id == rfq.id, SupplierQuote.supplier_id == option.supplier_id))
            quote_item = db.scalar(select(SupplierQuoteItem).where(SupplierQuoteItem.quote_id == quote.id))
            add(db, counts, QuoteComparisonItem, comparison_id=comparison.id,
                quote_id=quote.id, rfq_item_id=rfq_item.id, supplier_id=option.supplier_id,
                quoted_unit_price=quote_item.unit_price, total_amount=quote_item.unit_price * D(qty),
                moq_quantity=quote_item.moq_quantity, lead_days=quote_item.lead_days,
                payment_terms=quote_item.payment_terms, rank_no=1 if option.supplier_id == supplier_id else 2,
                selection_flag=1 if option.supplier_id == supplier_id else 0)

        fulfilled = stage in ("SETTLED", "RECEIVED")
        short = stage == "SHORT"
        actual = D(qty - (max(5, qty // 5) if short else 0)) if stage not in ("TRANSIT", "ORDERED") else D(0)
        order = add(db, counts, PurchaseOrder, po_no=business_no(number, "PO"), supplier_id=supplier_id,
            source_comparison_id=comparison.id, source_quote_id=selected_quote.id,
            source_request_id=request.id, department_id=request.department_id, buyer_id=buyer.id,
            order_amount=D(qty * price), currency_code="CNY", delivery_address="华东园区化学品仓",
            order_date=TODAY - timedelta(days=age + 10),
            expected_arrival_date=TODAY - timedelta(days=2) if stage == "TRANSIT" else TODAY + timedelta(days=4),
            status="COMPLETED" if fulfilled else "PARTIAL" if short else "ORDERED",
            supplier_confirmed_at=NOW - timedelta(days=age + 8), approved_at=NOW - timedelta(days=age + 9),
            note="采购用途：" + background)
        po_item = add(db, counts, PurchaseOrderItem, po_id=order.id, line_no=1,
            product_id=product.id, supplier_product_id=sp.id, source_quote_item_id=selected_quote_item.id,
            product_name_snapshot=product.product_name, supplier_model_snapshot=sp.supplier_model,
            order_quantity=D(qty), unit_id=product.unit_id, unit_price=D(price), tax_rate=D(13),
            planned_arrival_date=order.expected_arrival_date, received_quantity=actual,
            status="COMPLETED" if fulfilled else "OPEN", note=background)
        add(db, counts, PurchaseOrderEvent, po_id=order.id, event_type="ORDERED",
            event_time=NOW - timedelta(days=age + 8), operator_id=buyer.id,
            from_status="APPROVED", to_status="ORDERED", event_note=background)
        if stage == "ORDERED":
            continue
        delivery = add(db, counts, Delivery, delivery_no=business_no(number, "DLV"), po_id=order.id,
            supplier_id=supplier_id, shipment_date=TODAY - timedelta(days=age + 4),
            expected_arrival_date=order.expected_arrival_date,
            actual_arrival_date=TODAY - timedelta(days=age + 1) if actual else None,
            logistics_company="园区危化品配送服务", tracking_no=f"YQ202609{number:04d}",
            status="ACCEPTED" if fulfilled else "RECEIVED" if actual else "IN_TRANSIT",
            received_by=receiver.id if actual else None, received_at=NOW - timedelta(days=age + 1) if actual else None,
            note=background)
        delivery_item = add(db, counts, DeliveryItem, delivery_id=delivery.id, po_item_id=po_item.id,
            product_id=product.id, line_no=1, batch_no=batch_no(number),
            package_spec=product.packaging_spec, planned_quantity=D(qty), actual_quantity=actual,
            short_quantity=D(qty) - actual if actual else D(0), unit_id=product.unit_id,
            production_date=TODAY - timedelta(days=60 + number),
            expiry_date=TODAY + timedelta(days=240 + number % 180),
            document_complete=0 if stage == "DOCUMENT" else 1,
            note="到货批次按采购需求登记；" + background)
        if not actual:
            create_exception(db, counts, number, "OVERDUE", delivery, delivery_item,
                "计划到货日已过，需核查承运进度并更新领用计划。", buyer, departments["PROCUREMENT"].id)
            continue
        result = "PASSED" if fulfilled else "PARTIAL" if short else "PENDING"
        test_result, conclusion = acceptance_copy(stage, product.product_name, qty, int(actual), number)
        add(db, counts, QualityAcceptance, acceptance_no=business_no(number, "QA"), delivery_id=delivery.id,
            inspector_id=inspector.id, result=result, inspection_time=NOW - timedelta(days=age),
            test_result=test_result,
            certificate_complete=0 if stage == "DOCUMENT" else 1,
            conclusion=conclusion)
        if stage == "DOCUMENT":
            create_exception(db, counts, number, "DOCUMENT_MISSING", delivery, delivery_item,
                "随货质量证明未齐，暂不入库；通知供应商补齐批次文件。", inspector, departments["QUALITY"].id)
            continue
        if short:
            create_exception(db, counts, number, "SHORT_DELIVERY", delivery, delivery_item,
                f"订购 {qty}，实到 {actual}；差额 {D(qty)-actual} 待补发。", buyer, departments["PROCUREMENT"].id)
            replenish = add(db, counts, ReplenishmentRequest, replenishment_no=business_no(number, "REP"),
                supplier_id=supplier_id, source_po_id=order.id, source_delivery_id=delivery.id,
                applicant_id=buyer.id, reason="到货短交，依据原订单申请补足差额", status="APPROVED",
                approved_by=manager.id, approved_at=NOW)
            add(db, counts, ReplenishmentItem, replenishment_request_id=replenish.id,
                line_no=1, product_id=product.id, unit_id=product.unit_id,
                requested_quantity=D(qty)-actual, expected_date=TODAY + timedelta(days=6), status="OPEN")
        if stage in ("SETTLED", "RECEIVED", "SHORT"):
            wh_code = "WH-OXIDIZER" if "H2O2" in code else "WH-CORROSIVE" if code in ("PRD-HCL-AR", "PRD-SULFURIC-AR", "PRD-NAOH-AR", "PRD-ACETIC-AR") else "WH-26001"
            wh = warehouses[wh_code]
            loc = locations[wh.id]
            batch = add(db, counts, InventoryBatch, product_id=product.id,
                batch_no=delivery_item.batch_no, supplier_id=supplier_id, source_delivery_id=delivery.id,
                production_date=delivery_item.production_date, expiry_date=delivery_item.expiry_date,
                status="ACTIVE", note="到货批次资料已关联收货记录")
            bal = add(db, counts, InventoryBalance, warehouse_id=wh.id, location_id=loc.id,
                product_id=product.id, batch_id=batch.id, unit_id=product.unit_id,
                quantity=actual, locked_quantity=D(0), status="AVAILABLE")
            tx = add(db, counts, InventoryTransaction, transaction_no=business_no(number, "IN"),
                transaction_type="INBOUND", warehouse_id=wh.id, location_id=loc.id,
                product_id=product.id, batch_id=batch.id, unit_id=product.unit_id,
                quantity=actual, delivery_item_id=delivery_item.id,
                source_type="DELIVERY", source_id=delivery.id, operator_id=receiver.id,
                note="验收后入库；" + background)
            layer = add(db, counts, InventoryCostLayer, source_transaction_id=tx.id,
                warehouse_id=wh.id, location_id=loc.id, product_id=product.id, batch_id=batch.id,
                unit_id=product.unit_id, unit_cost=D(price), currency_code="CNY",
                original_quantity=actual, remaining_quantity=actual)
            balances.append((number, bal, layer, order, delivery, background))
            pr_item.fulfilled_quantity = actual
            pr_item.status = "FULFILLED" if fulfilled else "OPEN"
        if stage == "SETTLED":
            amount = order.order_amount
            rec = add(db, counts, FinanceReconciliation, reconciliation_no=business_no(number, "REC"),
                po_id=order.id, supplier_id=supplier_id, currency_code="CNY", total_amount=amount,
                status="CLOSED", created_by=finance.id, confirmed_by=manager.id,
                confirmed_at=NOW - timedelta(days=1), closed_at=NOW,
                note="按采购订单、到货记录及验收数量核对；" + background)
            net = (amount / D("1.13")).quantize(D("0.01"))
            add(db, counts, FinanceInvoice, invoice_no=business_no(number, "INV"), reconciliation_id=rec.id,
                po_id=order.id, supplier_id=supplier_id, invoice_number=f"FP202609{number:06d}",
                invoice_date=TODAY - timedelta(days=1), amount_excl_tax=net,
                tax_amount=amount-net, amount_incl_tax=amount, currency_code="CNY",
                status="VERIFIED", submitted_by=finance.id, verified_by=manager.id,
                verified_at=NOW, note="票面金额与订单及对账金额核对一致，附件待归档")
            add(db, counts, FinancePayment, payment_no=business_no(number, "PAY"), reconciliation_id=rec.id,
                po_id=order.id, supplier_id=supplier_id, amount=amount, currency_code="CNY",
                payment_method="BANK_TRANSFER", status="PAID", requested_by=finance.id,
                approved_by=manager.id, paid_by=finance.id, approved_at=NOW, paid_at=NOW,
                transaction_ref=f"FIN202609{number:06d}", note="付款登记金额与对账金额一致，银行回单待归档")
            add(db, counts, FinanceSettlement, settlement_no=business_no(number, "SET"),
                reconciliation_id=rec.id, po_id=order.id, supplier_id=supplier_id,
                settlement_amount=amount, currency_code="CNY", status="CONFIRMED",
                created_by=finance.id, confirmed_by=manager.id, confirmed_at=NOW,
                note="结算金额已与订单、发票及付款登记核对一致")

    # Draw from multiple batches with quantities proportional to stock. Completed
    # movements update balances and cost layers; drafts leave the ledger intact.
    for index, (number, bal, layer, order, delivery, background) in enumerate(balances, start=1):
        issue_qty = D(min(3 + index * 2, int(bal.quantity // 5)))
        if issue_qty > 0:
            issue = add(db, counts, InventoryIssueRequest, issue_no=business_no(number, "ISS"),
                applicant_id=buyer.id, department_id=departments["R_AND_D"].id,
                purpose="批次试验领用；" + background, status="COMPLETED",
                approved_by=receiver.id, approved_at=NOW, completed_at=NOW)
            add(db, counts, InventoryIssueItem, issue_request_id=issue.id, line_no=1,
                product_id=bal.product_id, warehouse_id=bal.warehouse_id, location_id=bal.location_id,
                batch_id=bal.batch_id, unit_id=bal.unit_id, requested_quantity=issue_qty,
                issued_quantity=issue_qty, status="COMPLETED")
            tx = add(db, counts, InventoryTransaction, transaction_no=business_no(number, "OUT"),
                transaction_type="OUTBOUND", warehouse_id=bal.warehouse_id, location_id=bal.location_id,
                product_id=bal.product_id, batch_id=bal.batch_id, unit_id=bal.unit_id,
                quantity=issue_qty, source_type="ISSUE_REQUEST", source_id=issue.id,
                operator_id=receiver.id, note=issue.purpose)
            add(db, counts, InventoryCostAllocation, transaction_id=tx.id,
                cost_layer_id=layer.id, quantity=issue_qty, unit_cost=layer.unit_cost,
                total_cost=issue_qty * layer.unit_cost)
            bal.quantity -= issue_qty
            layer.remaining_quantity -= issue_qty
        stocktake = add(db, counts, InventoryStocktakeRequest, stocktake_no=business_no(number, "STK"),
            applicant_id=receiver.id, warehouse_id=bal.warehouse_id, location_id=bal.location_id,
            purpose="月度账实核对；" + background, status="COMPLETED",
            approved_by=receiver.id, approved_at=NOW, completed_at=NOW)
        add(db, counts, InventoryStocktakeItem, stocktake_request_id=stocktake.id,
            line_no=1, product_id=bal.product_id, location_id=bal.location_id,
            batch_id=bal.batch_id, unit_id=bal.unit_id, book_quantity=bal.quantity,
            counted_quantity=bal.quantity, difference_quantity=D(0), status="COMPLETED",
            note="账面数量与本次盘点数量一致，无需调整")
        if number in (1, 4, 5, 8) or (number >= 27 and number % 5 == 0):
            ret = add(db, counts, InventoryReturnRequest, return_no=business_no(number, "RET"),
                supplier_id=order.supplier_id, po_id=order.id, delivery_id=delivery.id,
                applicant_id=receiver.id, reason="留样复核待确认；" + background, status="DRAFT")
            add(db, counts, InventoryReturnItem, return_request_id=ret.id,
                line_no=1, product_id=bal.product_id, warehouse_id=bal.warehouse_id,
                location_id=bal.location_id, batch_id=bal.batch_id, unit_id=bal.unit_id,
                requested_quantity=D(min(2 + number % 5, max(1, int(bal.quantity // 10)))), returned_quantity=D(0), status="OPEN",
                note="仅作评估，未实际退库")
        if (number in (1, 4, 5, 8) or (number >= 27 and number % 3 == 0)) and bal.warehouse_id == warehouses["WH-26001"].id:
            reserve = warehouses["WH-SOLVENT-RESERVE"]
            reserve_loc = locations[reserve.id]
            move_qty = D(min(6 + number, int(bal.quantity // 4)))
            transfer = add(db, counts, InventoryTransferRequest, transfer_no=business_no(number, "TRF"),
                applicant_id=receiver.id, purpose="同类仓区周转；" + background,
                status="COMPLETED", approved_by=receiver.id, approved_at=NOW, completed_at=NOW)
            add(db, counts, InventoryTransferItem, transfer_request_id=transfer.id, line_no=1,
                product_id=bal.product_id, source_warehouse_id=bal.warehouse_id,
                source_location_id=bal.location_id, target_warehouse_id=reserve.id,
                target_location_id=reserve_loc.id, batch_id=bal.batch_id, unit_id=bal.unit_id,
                requested_quantity=move_qty, transferred_quantity=move_qty, status="COMPLETED")
            out = add(db, counts, InventoryTransaction, transaction_no=business_no(number, "TO"),
                transaction_type="TRANSFER_OUT", warehouse_id=bal.warehouse_id,
                location_id=bal.location_id, product_id=bal.product_id, batch_id=bal.batch_id,
                unit_id=bal.unit_id, quantity=move_qty, source_type="TRANSFER_REQUEST",
                source_id=transfer.id, operator_id=receiver.id, note=transfer.purpose)
            in_tx = add(db, counts, InventoryTransaction, transaction_no=business_no(number, "TI"),
                transaction_type="TRANSFER_IN", warehouse_id=reserve.id, location_id=reserve_loc.id,
                product_id=bal.product_id, batch_id=bal.batch_id, unit_id=bal.unit_id,
                quantity=move_qty, source_type="TRANSFER_REQUEST", source_id=transfer.id,
                operator_id=receiver.id, note=transfer.purpose)
            add(db, counts, InventoryCostAllocation, transaction_id=out.id, cost_layer_id=layer.id,
                quantity=move_qty, unit_cost=layer.unit_cost, total_cost=move_qty * layer.unit_cost)
            add(db, counts, InventoryBalance, warehouse_id=reserve.id, location_id=reserve_loc.id,
                product_id=bal.product_id, batch_id=bal.batch_id, unit_id=bal.unit_id,
                quantity=move_qty, locked_quantity=D(0), status="AVAILABLE")
            add(db, counts, InventoryCostLayer, source_transaction_id=in_tx.id,
                warehouse_id=reserve.id, location_id=reserve_loc.id, product_id=bal.product_id,
                batch_id=bal.batch_id, unit_id=bal.unit_id, unit_cost=layer.unit_cost,
                currency_code="CNY", original_quantity=move_qty, remaining_quantity=move_qty)
            bal.quantity -= move_qty
            layer.remaining_quantity -= move_qty
    return counts


def create_exception(db, counts, number, kind, delivery, item, description, owner, department_id):
    exc = add(db, counts, OperationException, exception_no=business_no(number, "EX"),
        exception_type=kind, source_type="DELIVERY", source_id=delivery.id,
        po_id=delivery.po_id, delivery_id=delivery.id, delivery_item_id=item.id,
        responsible_department_id=department_id, owner_id=owner.id, severity="HIGH",
        description=description, status="OPEN", due_at=NOW + timedelta(days=2))
    task = add(db, counts, OperationTask, exception_id=exc.id,
        title="核查并处理" + ("短交" if kind == "SHORT_DELIVERY" else "随货文件" if kind == "DOCUMENT_MISSING" else "逾期到货"),
        assignee_id=owner.id, priority="HIGH", due_at=exc.due_at, status="OPEN")
    add(db, counts, OperationTaskComment, task_id=task.id,
        commenter_id=owner.id, content="已联系供应商核实，待反馈补交时间及处理方案。")
    add(db, counts, Notification, recipient_id=owner.id, related_type="OPERATION_EXCEPTION",
        related_id=exc.id, notification_type="EXCEPTION", title="待处理业务异常",
        content=description, is_read=0)


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-transaction", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        should_run = preflight(db)
        if not should_run:
            print(json.dumps({"already_applied": True}, ensure_ascii=False))
            return
        if not (args.apply or args.validate_transaction):
            print(json.dumps({"dry_run": True, "case_count": len(CASES)}, ensure_ascii=False))
            return
        counts = main_seed(db)
        result = verify(db)
        if args.validate_transaction:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({"rolled_back": args.validate_transaction, "created": counts, "verified": result},
            ensure_ascii=False, default=dict))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
