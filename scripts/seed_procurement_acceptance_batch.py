"""Create a traceable procurement acceptance batch in the local development DB.

The records exercise the buyer-to-manager approval screen. They are generated
acceptance data and must never be represented as actual procurement events.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.purchase_orders.model import (
    PurchaseOrder,
    PurchaseOrderApproval,
    PurchaseOrderEvent,
    PurchaseOrderItem,
)
from app.modules.purchase_requests.model import (
    PurchaseRequest,
    PurchaseRequestApproval,
    PurchaseRequestItem,
    Unit,
)
from app.modules.products.model import Product
from app.modules.rfqs.model import (
    QuoteComparison,
    QuoteComparisonItem,
    RFQ,
    RFQItem,
    RFQSupplier,
    SupplierQuote,
    SupplierQuoteItem,
)
from app.modules.suppliers.model import Supplier
from app.modules.suppliers.product_model import SupplierProduct
from app.modules.system.audit import add_audit_log
from app.modules.system.model import Department, User


def check_backup(path: Path, database: str) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "backups" / "mysql").resolve()):
        raise SystemExit("Backup must be under backups/mysql")
    if not resolved.is_file() or resolved.stat().st_size < 1024:
        raise SystemExit("A complete local development snapshot is required")
    with gzip.open(resolved, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
    if header.get("database") != database:
        raise SystemExit("Backup database does not match the target")
    created = datetime.strptime(header["created_at"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if abs((datetime.now(timezone.utc) - created).total_seconds()) > 3600:
        raise SystemExit("Backup must have been created within the last hour")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-transaction", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if (
        settings.app_env != "development"
        or settings.mysql_host not in {"localhost", "127.0.0.1"}
        or settings.mysql_database != "chemicalops"
    ):
        raise SystemExit("Only the local ChemicalOps development database may be changed")
    if args.apply or args.validate_transaction:
        if args.backup is None:
            raise SystemExit("A recent --backup is required")
        check_backup(args.backup, settings.mysql_database)

    day = date.today().strftime("%Y%m%d")
    request_nos = [f"QA-PR-{day}-{index:02d}" for index in range(1, 4)]
    with SessionLocal() as db:
        found = set(db.scalars(select(PurchaseRequest.request_no).where(PurchaseRequest.request_no.in_(request_nos))).all())
        if found == set(request_nos):
            print(json.dumps({"already_applied": True, "request_numbers": request_nos}, ensure_ascii=False))
            return
        if found:
            raise SystemExit(f"Partial batch already exists: {sorted(found)}")

        eligible_products = list(db.scalars(
            select(Product)
            .join(SupplierProduct, SupplierProduct.product_id == Product.id)
            .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
            .where(Product.status == "ACTIVE", SupplierProduct.status == "ACTIVE", Supplier.status == "ACTIVE")
            .group_by(Product.id)
            .having(func.count(SupplierProduct.id) >= 3)
            .order_by(Product.id)
            .limit(3)
        ).all())
        if len(eligible_products) != 3:
            raise SystemExit("Three active products with at least three active suppliers are required")
        rows = []
        for product in eligible_products:
            unit = db.get(Unit, product.unit_id)
            options = list(db.scalars(
                select(SupplierProduct)
                .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
                .where(
                    SupplierProduct.product_id == product.id,
                    SupplierProduct.status == "ACTIVE",
                    Supplier.status == "ACTIVE",
                )
                .order_by(SupplierProduct.id)
                .limit(3)
            ).all())
            if unit is None or unit.status != "ACTIVE" or len(options) != 3:
                raise SystemExit(f"Active unit or supplier offers are missing for {product.product_code}")
            rows.append((product, unit, options))

        if not (args.apply or args.validate_transaction):
            print(json.dumps({
                "dry_run": True,
                "request_numbers": request_nos,
                "products": [product.product_code for product, _, _ in rows],
                "supplier_quotes_per_case": 3,
                "pending_purchase_orders": 3,
            }, ensure_ascii=False))
            return

        users = {row.username: row for row in db.scalars(select(User)).all()}
        buyer = users.get("buyer")
        manager = users.get("procurement_manager")
        department = db.scalar(select(Department).where(Department.department_code == "PROCUREMENT"))
        if buyer is None or manager is None or department is None:
            raise SystemExit("Buyer, procurement manager, and procurement department are required")

        now = datetime.now().replace(microsecond=0)
        today = date.today()
        created = []
        try:
            for index, (product, unit, options) in enumerate(rows, start=1):
                qty = Decimal(24 + index * 12)
                request_day = today - timedelta(days=index + 1)
                expected = today + timedelta(days=7 + index)
                prefix = f"QA-{day}-{index:02d}"
                purpose = (
                    f"验收批次 {prefix}：核对{product.product_name}采购申请、供应商报价、比价和采购经理审批流程；"
                    "逐项检查规格、数量、计量单位、交期及随货资料要求。"
                )
                request = PurchaseRequest(
                    request_no=request_nos[index - 1],
                    applicant_id=buyer.id,
                    department_id=department.id,
                    purpose=purpose,
                    priority="NORMAL" if index != 3 else "HIGH",
                    budget_amount=Decimal("0"),
                    currency_code="CNY",
                    expected_date=expected,
                    status="APPROVED",
                    submitted_at=datetime.combine(request_day, datetime.min.time()).replace(hour=9),
                    approved_at=datetime.combine(request_day, datetime.min.time()).replace(hour=11),
                )
                db.add(request)
                db.flush()
                item = PurchaseRequestItem(
                    request_id=request.id,
                    line_no=1,
                    product_id=product.id,
                    requested_name=product.product_name,
                    technical_requirements=(
                        f"按产品规格 {product.model or '见产品主数据'} 供货；确认包装、纯度标识、批号和产品合格证明。"
                    ),
                    quantity=qty,
                    unit_id=unit.id,
                    budget_price=Decimal("0"),
                    expected_date=expected,
                    fulfilled_quantity=Decimal("0"),
                    status="OPEN",
                )
                db.add(item)
                approval = PurchaseRequestApproval(
                    request_id=request.id,
                    sequence_no=1,
                    node_code="PROCUREMENT_MANAGER",
                    node_name="采购经理审批",
                    approver_id=manager.id,
                    action="APPROVED",
                    opinion="验收链路预置状态；不代表实际业务审批。",
                    acted_at=request.approved_at,
                )
                db.add(approval)
                db.flush()

                rfq = RFQ(
                    rfq_no=f"QA-RFQ-{day}-{index:02d}",
                    source_request_id=request.id,
                    requester_id=buyer.id,
                    quote_deadline=datetime.combine(request_day + timedelta(days=1), datetime.min.time()).replace(hour=17),
                    requested_delivery_date=expected,
                    delivery_requirements="按订单计划交付；随货提供产品合格证明及批次资料。",
                    status="CLOSED",
                    sent_at=datetime.combine(request_day, datetime.min.time()).replace(hour=12),
                    closed_at=datetime.combine(request_day + timedelta(days=1), datetime.min.time()).replace(hour=17),
                )
                db.add(rfq)
                db.flush()
                rfq_item = RFQItem(
                    rfq_id=rfq.id,
                    line_no=1,
                    source_request_item_id=item.id,
                    product_id=product.id,
                    requested_name=product.product_name,
                    specification=product.model,
                    quantity=qty,
                    unit_id=unit.id,
                    required_delivery_date=expected,
                    technical_requirements=item.technical_requirements,
                )
                db.add(rfq_item)
                db.flush()

                quotes = []
                quote_lines = []
                for option_index, supplier_product in enumerate(options, start=1):
                    supplier = db.get(Supplier, supplier_product.supplier_id)
                    if supplier is None:
                        raise RuntimeError("Supplier offer has no supplier")
                    lead_days = supplier_product.standard_lead_days or supplier.default_lead_days or (4 + option_index)
                    base_price = Decimal("45") + Decimal(index * 3 + option_index * 2)
                    if product.product_code.startswith("PRD-ACETONITRILE"):
                        base_price += Decimal("40")
                    quoted_price = base_price + Decimal(option_index - 2) * Decimal("1.25")
                    db.add(RFQSupplier(
                        rfq_id=rfq.id,
                        supplier_id=supplier.id,
                        invited_at=rfq.sent_at,
                        response_status="QUOTED",
                        response_at=rfq.closed_at,
                        invitation_channel="EMAIL",
                        note="验收链路报价响应；非供应商实际报价。",
                    ))
                    quote = SupplierQuote(
                        quote_no=f"QA-QUO-{day}-{index:02d}-{option_index}",
                        rfq_id=rfq.id,
                        supplier_id=supplier.id,
                        quote_version=1,
                        quote_date=request_day + timedelta(days=1),
                        valid_until=expected + timedelta(days=10),
                        currency_code="CNY",
                        status="SUBMITTED",
                        received_by=buyer.id,
                        note="验收链路报价；非供应商正式报价。",
                    )
                    db.add(quote)
                    db.flush()
                    quote_item = SupplierQuoteItem(
                        quote_id=quote.id,
                        rfq_item_id=rfq_item.id,
                        supplier_product_id=supplier_product.id,
                        supplier_model=supplier_product.supplier_model or product.model,
                        quoted_quantity=qty,
                        unit_id=unit.id,
                        unit_price=quoted_price,
                        tax_rate=Decimal("13"),
                        moq_quantity=supplier_product.moq_quantity or Decimal("1"),
                        moq_unit_id=supplier_product.moq_unit_id or unit.id,
                        lead_days=lead_days,
                        payment_terms="验收后月结",
                        note="按询价数量、单位和交付要求录入验收数据。",
                    )
                    db.add(quote_item)
                    db.flush()
                    quotes.append((quote, quote_item, supplier_product, supplier, lead_days))
                    quote_lines.append(quote_item)

                chosen = min(quotes, key=lambda row: (row[1].unit_price, row[4], row[3].id))
                planned_budget_unit_price = (
                    max(row[1].unit_price for row in quotes) * Decimal("1.13")
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                request.budget_amount = (planned_budget_unit_price * qty).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                item.budget_price = planned_budget_unit_price
                comparison = QuoteComparison(
                    comparison_no=f"QA-CMP-{day}-{index:02d}",
                    rfq_id=rfq.id,
                    created_by=buyer.id,
                    selected_quote_id=chosen[0].id,
                    conclusion="验收链路按本次价格、交期和起订量字段形成排序；不作为实际定标结论。",
                    selection_reason="用于验证比价快照与采购订单来源关联。",
                    status="CONFIRMED",
                    confirmed_by=manager.id,
                    confirmed_at=rfq.closed_at,
                )
                db.add(comparison)
                db.flush()
                ordered_quotes = sorted(quotes, key=lambda row: (row[1].unit_price, row[4], row[3].id))
                for rank, (quote, quote_item, supplier_product, supplier, lead_days) in enumerate(ordered_quotes, start=1):
                    db.add(QuoteComparisonItem(
                        comparison_id=comparison.id,
                        quote_id=quote.id,
                        rfq_item_id=rfq_item.id,
                        supplier_id=supplier.id,
                        quoted_unit_price=quote_item.unit_price,
                        total_amount=(quote_item.unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                        moq_quantity=quote_item.moq_quantity,
                        lead_days=lead_days,
                        payment_terms=quote_item.payment_terms,
                        rank_no=rank,
                        selection_flag=1 if quote.id == chosen[0].id else 0,
                        note="履约历史分未生成；当前验收数据仅比较本次报价与交期。",
                    ))

                gross = (chosen[1].unit_price * qty * Decimal("1.13")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                order = PurchaseOrder(
                    po_no=f"QA-PO-{day}-{index:02d}",
                    supplier_id=chosen[3].id,
                    source_comparison_id=comparison.id,
                    source_quote_id=chosen[0].id,
                    source_request_id=request.id,
                    department_id=department.id,
                    buyer_id=buyer.id,
                    order_amount=gross,
                    currency_code="CNY",
                    delivery_address="ChemicalOps 本地验收收货区",
                    expected_arrival_date=expected,
                    status="DRAFT",
                    note="验收链路采购订单，待检查采购经理审批入口；不是实际采购订单。",
                    items=[PurchaseOrderItem(
                        line_no=1,
                        product_id=product.id,
                        supplier_product_id=chosen[2].id,
                        source_quote_item_id=chosen[1].id,
                        product_name_snapshot=product.product_name,
                        supplier_model_snapshot=chosen[1].supplier_model,
                        order_quantity=qty,
                        unit_id=unit.id,
                        unit_price=chosen[1].unit_price,
                        tax_rate=chosen[1].tax_rate,
                        planned_arrival_date=expected,
                        received_quantity=Decimal("0"),
                        status="OPEN",
                        note="未提交审批，未发生收货。",
                    )],
                )
                db.add(order)
                db.flush()
                order.events.extend([
                    PurchaseOrderEvent(
                        operator_id=buyer.id,
                        event_type="CREATED",
                        event_time=now,
                        from_status=None,
                        to_status="DRAFT",
                        event_note="验收链路生成采购订单草稿。",
                    ),
                    PurchaseOrderEvent(
                        operator_id=buyer.id,
                        event_type="SUBMITTED",
                        event_time=now + timedelta(milliseconds=1),
                        from_status="DRAFT",
                        to_status="APPROVING",
                        event_note="验收链路提交审批，用于检查角色边界。",
                    ),
                ])
                order.status = "APPROVING"
                order.approvals.append(PurchaseOrderApproval(
                    sequence_no=1,
                    node_code="PROCUREMENT_MANAGER",
                    node_name="采购经理审批",
                    action="PENDING",
                ))
                add_audit_log(
                    db,
                    actor_id=buyer.id,
                    action_type="CREATE",
                    resource_type="PURCHASE_ORDER",
                    resource_id=order.id,
                    request_summary=f"创建验收链路订单 {order.po_no}",
                    result_status="SUCCESS",
                )
                add_audit_log(
                    db,
                    actor_id=buyer.id,
                    action_type="SUBMIT",
                    resource_type="PURCHASE_ORDER",
                    resource_id=order.id,
                    request_summary=f"提交验收链路订单 {order.po_no} 审批",
                    result_status="SUCCESS",
                )
                created.append({
                    "request_no": request.request_no,
                    "rfq_no": rfq.rfq_no,
                    "comparison_no": comparison.comparison_no,
                    "po_no": order.po_no,
                    "status": order.status,
                    "product": product.product_name,
                    "quantity": str(qty),
                    "unit": unit.unit_name,
                    "supplier_quotes": len(quotes),
                    "order_amount": str(gross),
                })

            db.flush()
            assert len(created) == 3 and all(row["status"] == "APPROVING" for row in created)
            if args.validate_transaction:
                db.rollback()
            else:
                db.commit()
        except Exception:
            db.rollback()
            raise

    print(json.dumps({"rolled_back": args.validate_transaction, "created": created}, ensure_ascii=False))


if __name__ == "__main__":
    main()
