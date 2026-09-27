"""逾期扫描任务。"""

from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.observability import metrics, observe_duration
from app.modules.jobs.model import SchedulerJobRun

from app.modules.deliveries.model import Delivery
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.notifications.service import notify_users
from app.modules.operation_exceptions.service import create_automatic_exception
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.products.model import Product
from app.modules.system.model import Role, User, UserRole


def list_job_runs(db: Session, *, limit: int = 50) -> list[SchedulerJobRun]:
    """按开始时间倒序查询后台任务运行历史。"""

    return list(db.scalars(select(SchedulerJobRun).order_by(desc(SchedulerJobRun.started_at), desc(SchedulerJobRun.id)).limit(limit)).all())


def start_scheduled_run(db: Session, run_id: str, *, task_name: str = "overdue_scan") -> SchedulerJobRun:
    """在开始业务处理前持久化一次后台执行记录。"""

    run = SchedulerJobRun(run_id=run_id, task_name=task_name, status="RUNNING", attempt_count=0)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_scheduled_run(
    db: Session,
    run: SchedulerJobRun,
    *,
    attempt_count: int | None = None,
    result: dict[str, int] | None = None,
    error_type: str | None = None,
) -> None:
    """记录尝试次数及任务成功或失败结果。"""

    if attempt_count is not None:
        run.attempt_count = attempt_count
    if result is not None:
        run.status = "SUCCEEDED"
        run.result_json = result
        run.error_type = None
        run.finished_at = datetime.now()
    elif error_type is not None:
        run.status = "FAILED"
        run.error_type = error_type[:128]
        run.finished_at = datetime.now()
    db.commit()


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


def scan_expiring_inventory(db: Session, actor: User) -> dict[str, int]:
    """为 30 天内到期且仍有库存的批次创建去重异常并通知相关角色。"""

    today = date.today()
    deadline = today + timedelta(days=30)
    with observe_duration("scheduler_job_duration_seconds", labels={"job": "inventory_expiry_scan"}):
        rows = db.execute(
            select(
                InventoryBatch,
                Product.product_name,
                func.sum(InventoryBalance.quantity).label("quantity"),
            )
            .join(InventoryBalance, InventoryBalance.batch_id == InventoryBatch.id)
            .join(Product, Product.id == InventoryBatch.product_id)
            .where(
                InventoryBatch.status == "ACTIVE",
                InventoryBatch.expiry_date.is_not(None),
                InventoryBatch.expiry_date <= deadline,
                InventoryBalance.quantity > 0,
            )
            .group_by(*InventoryBatch.__table__.columns, Product.id, Product.product_name)
            .order_by(InventoryBatch.expiry_date, InventoryBatch.id)
        ).all()
    created_count = 0
    for batch, product_name, quantity in rows:
        days_remaining = (batch.expiry_date - today).days
        level = "已过期" if days_remaining < 0 else "即将到期"
        severity = "HIGH" if days_remaining <= 7 else "MEDIUM"
        description = (
            f"产品 {product_name} 批次 {batch.batch_no} {level}，有效期至 {batch.expiry_date}，"
            f"当前账面库存 {quantity}；请核实并按仓储流程处理。"
        )
        exception = create_automatic_exception(
            db,
            actor,
            exception_type="INVENTORY_EXPIRY",
            source_type="INVENTORY_BATCH",
            source_id=batch.id,
            severity=severity,
            description=description,
        )
        if exception is not None:
            created_count += 1
            notify_users(
                db,
                role_codes=["WAREHOUSE", "PROCUREMENT_MANAGER"],
                notification_type="INVENTORY_EXPIRY_CREATED",
                title="发现临期库存批次",
                content=description,
                related_type="OPERATION_EXCEPTION",
                related_id=exception.id,
            )
    db.commit()
    result = {"scanned_count": len(rows), "created_count": created_count}
    metrics.increment("scheduler_jobs", labels={"job": "inventory_expiry_scan", "status": "success"})
    return result


def scan_active_alerts(db: Session, actor: User) -> dict[str, int]:
    """运行当前有明确业务口径的到货逾期与库存临期扫描。"""

    overdue = scan_overdue_deliveries(db, actor)
    expiry = scan_expiring_inventory(db, actor)
    return {
        "overdue_scanned_count": overdue["scanned_count"],
        "overdue_created_count": overdue["created_count"],
        "inventory_expiry_scanned_count": expiry["scanned_count"],
        "inventory_expiry_created_count": expiry["created_count"],
    }


def run_scheduled_alert_scan() -> None:
    """以系统管理员身份执行一次定时扫描并记录运行结果。"""

    db = SessionLocal()
    run: SchedulerJobRun | None = None
    try:
        run = start_scheduled_run(db, uuid4().hex, task_name="business_alert_scan")
        actor = db.scalar(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.status == "ACTIVE", Role.status == "ACTIVE", Role.role_code == "SYS_ADMIN")
            .order_by(User.id)
            .limit(1)
        )
        if actor is None:
            raise RuntimeError("没有可用的系统管理员账号来记录自动异常")
        result = scan_active_alerts(db, actor)
        update_scheduled_run(db, run, result=result)
    except Exception as exc:
        db.rollback()
        if run is not None:
            current_run = db.get(SchedulerJobRun, run.id)
            if current_run is not None:
                update_scheduled_run(db, current_run, error_type=exc.__class__.__name__)
        raise
    finally:
        db.close()
