"""Dashboard 基础统计查询。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinancePayment, FinanceReconciliation
from app.modules.inventory.model import InventoryBalance, InventoryBatch, Warehouse, WarehouseLocation
from app.modules.inventory.model import InventoryTransaction
from app.modules.inventory_cost.model import InventoryCostAllocation
from app.modules.inventory_cost.service import list_expiry_alerts
from app.modules.operation_exceptions.model import OperationException
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.suppliers.model import Supplier
from app.core.errors import BusinessValidationError


def get_overview(db: Session):
    """查询 Dashboard 首页所需的聚合指标。"""
    total_orders = db.scalar(select(func.count(PurchaseOrder.id))) or 0
    in_progress = db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status.in_(("DRAFT", "APPROVING", "APPROVED", "ORDERED", "PARTIAL")))) or 0
    overdue = db.scalar(select(func.count(Delivery.id)).where(Delivery.status == "IN_TRANSIT", Delivery.expected_arrival_date.is_not(None), Delivery.expected_arrival_date < date.today())) or 0
    quantity = db.scalar(select(func.coalesce(func.sum(InventoryBalance.quantity), 0))) or 0
    inventory_units = db.execute(
        select(
            InventoryBalance.unit_id,
            Unit.unit_code,
            Unit.unit_name,
            func.coalesce(func.sum(InventoryBalance.quantity), 0),
        )
        .join(Unit, Unit.id == InventoryBalance.unit_id)
        .group_by(InventoryBalance.unit_id, Unit.unit_code, Unit.unit_name)
        .order_by(InventoryBalance.unit_id)
    ).all()
    exceptions = db.scalar(select(func.count(OperationException.id)).where(OperationException.status.in_(("OPEN", "PROCESSING")))) or 0
    reconciliations = db.scalar(select(func.count(FinanceReconciliation.id)).where(FinanceReconciliation.status == "CONFIRMED")) or 0
    paid_amount = db.scalar(select(func.coalesce(func.sum(FinancePayment.amount), 0)).where(FinancePayment.status == "PAID")) or 0
    return {"purchase_orders_total": total_orders, "purchase_orders_in_progress": in_progress, "deliveries_overdue": overdue, "inventory_quantity": Decimal(quantity), "inventory_units": [{"unit_id": unit_id, "unit_code": unit_code, "unit_name": unit_name, "quantity": Decimal(unit_quantity)} for unit_id, unit_code, unit_name, unit_quantity in inventory_units], "open_exceptions": exceptions, "confirmed_reconciliations": reconciliations, "paid_amount": Decimal(paid_amount), "expiry_alerts": len(list_expiry_alerts(db, days=30))}


def get_report(db: Session, *, date_from: date | None, date_to: date | None) -> dict:
    """按订单日期聚合采购订单和供应商履约指标。"""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise BusinessValidationError("统计开始日期不能晚于结束日期")

    order_conditions = []
    delivery_conditions = [
        Delivery.status == "IN_TRANSIT",
        Delivery.expected_arrival_date.is_not(None),
        Delivery.expected_arrival_date < date.today(),
    ]
    if date_from is not None:
        # 采购趋势/状态/供应商金额都按业务上的「下单日期」统计，
        # created_at 只是种子落库时间，会把历史订单全部挤到同一天。
        order_conditions.append(PurchaseOrder.order_date >= date_from)
        delivery_conditions.append(func.date(Delivery.created_at) >= date_from)
    if date_to is not None:
        order_conditions.append(PurchaseOrder.order_date <= date_to)
        delivery_conditions.append(func.date(Delivery.created_at) <= date_to)

    trend_start = date_from or date.fromordinal(date.today().toordinal() - 29)
    trend_end = date_to or date.today()
    trend_rows = db.execute(
        select(
            PurchaseOrder.order_date,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.order_amount), 0),
        )
        .where(PurchaseOrder.order_date.is_not(None), PurchaseOrder.order_date >= trend_start, PurchaseOrder.order_date <= trend_end)
        .group_by(PurchaseOrder.order_date)
        .order_by(PurchaseOrder.order_date)
    ).all()
    trend_by_date = {
        trend_date: {"order_count": count, "order_amount": Decimal(amount)}
        for trend_date, count, amount in trend_rows
    }
    trend_days = max(0, (trend_end - trend_start).days)
    order_trend = []
    for offset in range(trend_days + 1):
        current_date = trend_start.fromordinal(trend_start.toordinal() + offset)
        metric = trend_by_date.get(current_date, {"order_count": 0, "order_amount": Decimal("0")})
        order_trend.append({"date": current_date, **metric})

    status_rows = db.execute(
        select(
            PurchaseOrder.status,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.order_amount), 0),
        )
        .where(*order_conditions)
        .group_by(PurchaseOrder.status)
        .order_by(PurchaseOrder.status)
    ).all()
    supplier_rows = db.execute(
        select(
            PurchaseOrder.supplier_id,
            Supplier.supplier_name,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(PurchaseOrder.order_amount), 0),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(*order_conditions)
        .group_by(PurchaseOrder.supplier_id, Supplier.supplier_name)
        .order_by(func.sum(PurchaseOrder.order_amount).desc(), PurchaseOrder.supplier_id)
    ).all()
    overdue_rows = db.execute(
        select(Delivery.supplier_id, func.count(Delivery.id))
        .where(*delivery_conditions)
        .group_by(Delivery.supplier_id)
    ).all()
    overdue_by_supplier = {supplier_id: count for supplier_id, count in overdue_rows}
    cost_rows = db.execute(
        select(
            Product.id,
            Product.product_name,
            func.coalesce(func.sum(InventoryCostAllocation.quantity), 0),
            func.coalesce(func.sum(InventoryCostAllocation.total_cost), 0),
        )
        .join(InventoryTransaction, InventoryTransaction.product_id == Product.id)
        .join(InventoryCostAllocation, InventoryCostAllocation.transaction_id == InventoryTransaction.id)
        .where(InventoryTransaction.transaction_type == "OUTBOUND", *(
            [func.date(InventoryTransaction.created_at) >= date_from] if date_from is not None else []
        ), *(
            [func.date(InventoryTransaction.created_at) <= date_to] if date_to is not None else []
        ))
        .group_by(Product.id, Product.product_name)
        .order_by(func.sum(InventoryCostAllocation.total_cost).desc(), Product.id)
    ).all()
    today = date.today()
    expiry_deadline = date.fromordinal(today.toordinal() + 30)
    expiry_rows = db.execute(
        select(
            InventoryBalance.id,
            Product.product_name,
            InventoryBatch.batch_no,
            Warehouse.warehouse_name,
            WarehouseLocation.location_name,
            InventoryBalance.quantity,
            Unit.unit_name,
            InventoryBatch.expiry_date,
        )
        .join(InventoryBatch, InventoryBatch.product_id == Product.id)
        .join(InventoryBalance, InventoryBalance.batch_id == InventoryBatch.id)
        .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
        .join(Unit, Unit.id == InventoryBalance.unit_id)
        .where(
            InventoryBatch.expiry_date.is_not(None),
            InventoryBatch.expiry_date <= expiry_deadline,
            InventoryBalance.quantity > 0,
        )
        .order_by(InventoryBatch.expiry_date, Product.id, InventoryBalance.id)
        .limit(8)
    ).all()
    pending_tasks = [
        {
            "task_type": "PURCHASE_ORDER_APPROVAL",
            "task_count": db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "APPROVING")) or 0,
        },
        {
            "task_type": "QUALITY_ACCEPTANCE",
            "task_count": db.scalar(select(func.count(QualityAcceptance.id)).where(QualityAcceptance.result.in_(("PENDING", "REINSPECTION")))) or 0,
        },
        {
            "task_type": "DELIVERY_CONFIRMATION",
            "task_count": db.scalar(select(func.count(Delivery.id)).where(Delivery.status == "IN_TRANSIT")) or 0,
        },
        {
            "task_type": "OPEN_EXCEPTION",
            "task_count": db.scalar(select(func.count(OperationException.id)).where(OperationException.status.in_(("OPEN", "PROCESSING")))) or 0,
        },
        {
            "task_type": "INVENTORY_EXPIRY",
            "task_count": len(list_expiry_alerts(db, days=30)),
        },
    ]
    return {
        "date_from": date_from,
        "date_to": date_to,
        "order_trend": order_trend,
        "order_statuses": [
            {"status": status, "order_count": count, "order_amount": Decimal(amount)}
            for status, count, amount in status_rows
        ],
        "supplier_performance": [
            {
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "order_count": count,
                "order_amount": Decimal(amount),
                "overdue_deliveries": overdue_by_supplier.get(supplier_id, 0),
            }
            for supplier_id, supplier_name, count, amount in supplier_rows
        ],
        "inventory_costs": [
            {"product_id": product_id, "product_name": product_name, "outbound_quantity": Decimal(quantity), "outbound_cost": Decimal(cost)}
            for product_id, product_name, quantity, cost in cost_rows
        ],
        "pending_tasks": pending_tasks,
        "inventory_alerts": [
            {
                "balance_id": balance_id,
                "product_name": product_name,
                "batch_no": batch_no,
                "warehouse_name": warehouse_name,
                "location_name": location_name,
                "quantity": Decimal(quantity),
                "unit_name": unit_name,
                "expiry_date": expiry_date,
                "days_remaining": (expiry_date - today).days,
                "level": "EXPIRED" if (expiry_date - today).days < 0 else "URGENT" if (expiry_date - today).days <= 7 else "WARNING",
            }
            for balance_id, product_name, batch_no, warehouse_name, location_name, quantity, unit_name, expiry_date in expiry_rows
        ],
    }
