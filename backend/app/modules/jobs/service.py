"""逾期扫描任务。"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.observability import metrics, observe_duration
from app.modules.jobs.model import SchedulerJobRun

from app.modules.deliveries.model import Delivery
from app.modules.inventory.model import InventoryBalance, InventoryBatch
from app.modules.notifications.service import notify_users
from app.modules.operation_exceptions.model import OperationException
from app.modules.operation_exceptions.service import close_recovered_low_stock_alert, create_automatic_exception
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.products.model import Product
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.purchase_requests.model import Unit
from app.modules.system.model import Role, User, UserRole


LOGGER = logging.getLogger("chemicalops.jobs")


def _publish_suggestion(db: Session, exception: OperationException) -> None:
    """事件建议属于附加能力，失败不能影响业务提醒和扫描结果。"""

    try:
        from app.modules.ai.proactive import publish_exception_suggestion

        publish_exception_suggestion(db, exception)
    except Exception:
        LOGGER.exception("运营建议生成失败 exception_id=%s", exception.id)


def list_job_runs(db: Session, *, limit: int = 50) -> list[SchedulerJobRun]:
    """按开始时间倒序查询后台任务运行历史。"""

    return list(db.scalars(select(SchedulerJobRun).order_by(desc(SchedulerJobRun.started_at), desc(SchedulerJobRun.id)).limit(limit)).all())


def start_scheduled_run(db: Session, run_id: str, *, task_name: str = "overdue_scan", commit: bool = True) -> SchedulerJobRun:
    """在开始业务处理前持久化一次后台执行记录。"""

    run = SchedulerJobRun(run_id=run_id, task_name=task_name, status="RUNNING", attempt_count=0)
    db.add(run)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(run)
    return run


def update_scheduled_run(
    db: Session,
    run: SchedulerJobRun,
    *,
    attempt_count: int | None = None,
    result: dict[str, Any] | None = None,
    error_type: str | None = None,
    commit: bool = True,
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
    if commit:
        db.commit()
    else:
        db.flush()


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
            _publish_suggestion(db, exception)
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
            _publish_suggestion(db, exception)
    db.commit()
    result = {"scanned_count": len(rows), "created_count": created_count}
    metrics.increment("scheduler_jobs", labels={"job": "inventory_expiry_scan", "status": "success"})
    return result


def scan_pending_quality_acceptances(
    db: Session,
    actor: User,
    *,
    threshold_hours: int = 24,
) -> dict[str, int]:
    """提醒已收货且超过配置时限仍未完成的质量验收。"""

    now = datetime.now()
    threshold = max(1, threshold_hours)
    cutoff = now - timedelta(hours=threshold)
    with observe_duration("scheduler_job_duration_seconds", labels={"job": "quality_pending_scan"}):
        rows = db.execute(
            select(QualityAcceptance, Delivery.delivery_no, PurchaseOrder.id, PurchaseOrder.po_no)
            .join(Delivery, Delivery.id == QualityAcceptance.delivery_id)
            .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
            .where(
                QualityAcceptance.result == "PENDING",
                QualityAcceptance.created_at <= cutoff,
                Delivery.status == "INSPECTING",
            )
            .order_by(QualityAcceptance.created_at, QualityAcceptance.id)
        ).all()
    created_count = 0
    for acceptance, delivery_no, po_id, po_no in rows:
        waiting_hours = max(0, int((now - acceptance.created_at).total_seconds() // 3600))
        severity = "HIGH" if waiting_hours >= threshold * 3 else "MEDIUM"
        description = (
            f"质量验收 {acceptance.acceptance_no} 已等待约 {waiting_hours} 小时仍未完成；"
            f"关联到货单 {delivery_no}、采购订单 {po_no}。请质量人员核实验收进度。"
        )
        exception = create_automatic_exception(
            db,
            actor,
            exception_type="QUALITY_PENDING",
            source_type="QUALITY_ACCEPTANCE",
            source_id=acceptance.id,
            po_id=po_id,
            delivery_id=acceptance.delivery_id,
            owner_id=acceptance.inspector_id,
            severity=severity,
            description=description,
        )
        if exception is not None:
            created_count += 1
            notify_users(
                db,
                recipient_ids=[acceptance.inspector_id],
                role_codes=["QUALITY", "PROCUREMENT_MANAGER"],
                notification_type="QUALITY_PENDING_CREATED",
                title="质量验收等待时间较长",
                content=description,
                related_type="OPERATION_EXCEPTION",
                related_id=exception.id,
            )
            _publish_suggestion(db, exception)
    db.commit()
    result = {"scanned_count": len(rows), "created_count": created_count}
    metrics.increment("scheduler_jobs", labels={"job": "quality_pending_scan", "status": "success"})
    return result


def scan_low_inventory(db: Session, actor: User) -> dict[str, int]:
    """Compare available stock with product thresholds in the same configured unit."""

    available_expression = func.coalesce(
        func.sum(
            case(
                (
                    and_(InventoryBalance.unit_id == Product.unit_id, InventoryBalance.status == "AVAILABLE"),
                    case(
                        (
                            InventoryBalance.quantity > InventoryBalance.locked_quantity,
                            InventoryBalance.quantity - InventoryBalance.locked_quantity,
                        ),
                        else_=0,
                    ),
                ),
                else_=0,
            )
        ),
        0,
    )
    mismatched_unit_count = func.coalesce(
        func.sum(case((and_(InventoryBalance.quantity > 0, InventoryBalance.unit_id != Product.unit_id), 1), else_=0)),
        0,
    )
    with observe_duration("scheduler_job_duration_seconds", labels={"job": "low_inventory_scan"}):
        rows = db.execute(
            select(Product, Unit.unit_name, available_expression, mismatched_unit_count)
            .join(Unit, Unit.id == Product.unit_id)
            .outerjoin(InventoryBalance, InventoryBalance.product_id == Product.id)
            .where(
                Product.status == "ACTIVE",
                Product.safety_stock_quantity.is_not(None),
                Product.safety_stock_quantity > 0,
            )
            .group_by(Product.id, Unit.unit_name)
            .order_by(Product.product_name, Product.id)
        ).all()

    states: dict[int, tuple[Product, str, Decimal, int]] = {}
    for product, unit_name, available, mismatch_count in rows:
        states[product.id] = (product, unit_name, Decimal(str(available or 0)), int(mismatch_count or 0))

    existing = list(
        db.scalars(
            select(OperationException)
            .where(
                OperationException.exception_type == "LOW_STOCK",
                OperationException.source_type == "PRODUCT",
                OperationException.source_id.in_(states.keys()) if states else False,
            )
            .order_by(OperationException.created_at.desc(), OperationException.id.desc())
        ).all()
    )
    latest_by_product: dict[int, OperationException] = {}
    for exception in existing:
        latest_by_product.setdefault(exception.source_id, exception)

    # Close untouched alerts on recovery, preserving the normal state transitions and audit entries.
    recovered_count = 0
    for product_id, exception in latest_by_product.items():
        product_state = states.get(product_id)
        if product_state is None:
            continue
        product, _unit_name, available, mismatch_count = product_state
        if (
            mismatch_count == 0
            and available >= Decimal(str(product.safety_stock_quantity))
            and close_recovered_low_stock_alert(db, actor, exception.id)
        ):
            recovered_count += 1

    created_count = 0
    skipped_unit_mismatch_count = 0
    for product, unit_name, available, mismatch_count in states.values():
        if mismatch_count:
            skipped_unit_mismatch_count += 1
            continue
        threshold = Decimal(str(product.safety_stock_quantity))
        if available >= threshold:
            continue
        previous = latest_by_product.get(product.id)
        if previous is not None and not (
            previous.status == "CLOSED"
            and (previous.closing_note or "").startswith("系统自动关闭：可用库存已恢复")
        ):
            continue
        description = (
            f"产品 {product.product_name} 当前可用库存 {available} {unit_name}，"
            f"低于已登记安全库存阈值 {threshold} {unit_name}；请核实库存及在途采购后再决定是否补货。"
        )
        exception = create_automatic_exception(
            db,
            actor,
            exception_type="LOW_STOCK",
            source_type="PRODUCT",
            source_id=product.id,
            severity="HIGH" if available == 0 else "MEDIUM",
            description=description,
        )
        if exception is not None:
            created_count += 1
            notify_users(
                db,
                role_codes=["WAREHOUSE", "PROCUREMENT_MANAGER"],
                notification_type="LOW_STOCK_CREATED",
                title="发现低库存产品",
                content=description,
                related_type="OPERATION_EXCEPTION",
                related_id=exception.id,
            )
            _publish_suggestion(db, exception)
    db.commit()
    result = {
        "scanned_count": len(states),
        "created_count": created_count,
        "recovered_count": recovered_count,
        "skipped_unit_mismatch_count": skipped_unit_mismatch_count,
    }
    metrics.increment("scheduler_jobs", labels={"job": "low_inventory_scan", "status": "success"})
    return result


def scan_active_alerts(db: Session, actor: User) -> dict[str, int]:
    """运行到货逾期、库存临期和超时待验收扫描。"""

    overdue = scan_overdue_deliveries(db, actor)
    expiry = scan_expiring_inventory(db, actor)
    pending_quality = scan_pending_quality_acceptances(
        db,
        actor,
        threshold_hours=get_settings().quality_pending_alert_hours,
    )
    low_inventory = scan_low_inventory(db, actor)
    return {
        "overdue_scanned_count": overdue["scanned_count"],
        "overdue_created_count": overdue["created_count"],
        "inventory_expiry_scanned_count": expiry["scanned_count"],
        "inventory_expiry_created_count": expiry["created_count"],
        "quality_pending_scanned_count": pending_quality["scanned_count"],
        "quality_pending_created_count": pending_quality["created_count"],
        "low_inventory_scanned_count": low_inventory["scanned_count"],
        "low_inventory_created_count": low_inventory["created_count"],
        "low_inventory_recovered_count": low_inventory["recovered_count"],
        "low_inventory_skipped_unit_mismatch_count": low_inventory["skipped_unit_mismatch_count"],
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
