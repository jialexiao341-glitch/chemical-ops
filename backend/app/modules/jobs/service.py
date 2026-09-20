"""逾期扫描任务。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability import metrics, observe_duration

from app.modules.deliveries.model import Delivery
from app.modules.notifications.service import notify_users
from app.modules.operation_exceptions.service import create_automatic_exception
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.model import User


def scan_overdue_deliveries(db: Session, actor: User) -> dict[str, int]:
    """扫描逾期未到货记录，生成去重异常并发送站内通知。"""
    with observe_duration("scheduler_job_duration_seconds", labels={"job": "overdue_scan"}):
        deliveries = list(db.scalars(select(Delivery).where(Delivery.status == "IN_TRANSIT", Delivery.expected_arrival_date.is_not(None), Delivery.expected_arrival_date < date.today())).all())
    created_count = 0
    for delivery in deliveries:
        order = db.get(PurchaseOrder, delivery.po_id)
        exception = create_automatic_exception(db, actor, exception_type="OVERDUE", source_type="DELIVERY", source_id=delivery.id, po_id=delivery.po_id, delivery_id=delivery.id, owner_id=order.buyer_id if order is not None else None, severity="HIGH", description=f"到货单 {delivery.delivery_no} 已超过预计到货日期 {delivery.expected_arrival_date}")
        if exception is not None:
            created_count += 1
            notify_users(db, recipient_ids=[order.buyer_id] if order is not None else [], role_codes=["PROCUREMENT_MANAGER", "WAREHOUSE"], notification_type="OVERDUE_CREATED", title="发现逾期到货", content=exception.description, related_type="OPERATION_EXCEPTION", related_id=exception.id)
    db.commit()
    result = {"scanned_count": len(deliveries), "created_count": created_count}
    metrics.increment("scheduler_jobs", labels={"job": "overdue_scan", "status": "success"})
    return result
