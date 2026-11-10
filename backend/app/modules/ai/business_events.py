"""业务事件记录与确定性分派。

业务服务在自身事务内写入事件；程序按事件类型、业务状态、权限和变化幅度
决定是否生成待办与提醒。这里不调用模型，也不执行任何业务写入。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


EVENT_PURCHASE_ORDER_ETA_CHANGED = "PURCHASE_ORDER_ETA_CHANGED"
SUBJECT_PURCHASE_ORDER = "PURCHASE_ORDER"
TASK_DELIVERY_CHANGE = "DELIVERY_CHANGE"

# 当前只接入交期变化；新增事件类型必须同时补快速过滤和影响摘要。
FAST_PATH_EVENT_TYPES = frozenset({EVENT_PURCHASE_ORDER_ETA_CHANGED})
ACTIVE_ORDER_STATUSES = frozenset({"ORDERED", "PARTIAL"})
DELIVERY_NOTIFY_ROLES = ("PROCUREMENT_MANAGER",)


class AIBusinessEvent(Base):
    """业务事件的追加式记录；同一业务变更只能产生一条事件。"""

    __tablename__ = "ai_business_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_ai_business_event_dedup"),
        UniqueConstraint("event_id", name="uq_ai_business_event_id"),
        Index("ix_ai_business_event_subject", "subject_type", "subject_id", "id"),
        Index("ix_ai_business_event_status", "triage_status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dedup_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="business")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    impact: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    triage_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    triage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _quantity_text(value: Decimal | int | float | None) -> str:
    """保留业务精度，不使用浮点格式化。"""
    if value is None:
        return "0"
    return format(Decimal(str(value)).normalize(), "f")


def build_delivery_change_impact(
    *,
    po_no: str,
    order_status: str,
    previous: date | None,
    expected: date,
    required_date: date | None,
    lines: list[dict[str, Any]],
    in_transit_deliveries: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    """只使用已保存的业务事实生成影响摘要，不推断未登记的数据。"""
    delta_days = (expected - previous).days if previous is not None else None
    if delta_days is None:
        direction = "INITIAL"
    elif delta_days > 0:
        direction = "DELAY"
    elif delta_days < 0:
        direction = "EARLY"
    else:
        direction = "UNCHANGED"
    overdue = expected < today
    required_gap = (expected - required_date).days if required_date is not None else None
    if required_gap is not None and required_gap > 0:
        risk_level = "HIGH"
    elif delta_days is not None and delta_days >= 7:
        risk_level = "HIGH"
    elif direction == "DELAY" or overdue:
        risk_level = "NORMAL"
    else:
        risk_level = "LOW"

    remaining_lines = [
        {
            "line_no": line["line_no"],
            "product_name": line["product_name"],
            "remaining_quantity": _quantity_text(line["remaining_quantity"]),
            "unit_id": line["unit_id"],
        }
        for line in lines
        if Decimal(str(line["remaining_quantity"])) > 0
    ]
    by_unit: dict[str, str] = {}
    for line in remaining_lines:
        key = str(line["unit_id"])
        by_unit[key] = _quantity_text(Decimal(by_unit.get(key, "0")) + Decimal(line["remaining_quantity"]))

    if direction == "INITIAL":
        change_text = f"初次登记预计到货 {expected.isoformat()}"
    elif direction == "UNCHANGED":
        change_text = f"预计到货维持 {expected.isoformat()}"
    else:
        label = "延后" if direction == "DELAY" else "提前"
        change_text = f"预计到货 {previous.isoformat()} → {expected.isoformat()}（{label} {abs(delta_days)} 天）"
    if required_gap is not None and required_gap > 0:
        change_text += f"；已晚于申请期望到货 {required_date.isoformat()} {required_gap} 天"
    if overdue:
        change_text += "；新日期已早于当前业务日，需核对是否已实际到货"

    return {
        "po_no": po_no,
        "order_status": order_status,
        "previous_date": _iso(previous),
        "expected_date": _iso(expected),
        "delta_days": delta_days,
        "direction": direction,
        "overdue_flag": overdue,
        "required_date": _iso(required_date),
        "required_gap_days": required_gap,
        "risk_level": risk_level,
        "remaining_line_count": len(remaining_lines),
        "remaining_by_unit": by_unit,
        "remaining_lines": remaining_lines[:20],
        "in_transit_count": len(in_transit_deliveries),
        "in_transit_expected_dates": sorted(
            item["expected_arrival_date"] for item in in_transit_deliveries
            if item.get("expected_arrival_date") is not None
        )[:10],
        "change_text": change_text,
        "analysis_mode": "DETERMINISTIC",
    }


def _required_date(db: Session, order) -> date | None:
    """读取申请期望到货日期；缺失时不补造。"""
    if order.source_request_id is None:
        return None
    from app.modules.purchase_requests.model import PurchaseRequest
    request = db.get(PurchaseRequest, order.source_request_id)
    return request.expected_date if request is not None else None


def _order_impact(db: Session, order, update, today: date) -> dict[str, Any]:
    from app.modules.deliveries.model import Delivery
    deliveries = list(db.scalars(select(Delivery).where(
        Delivery.po_id == order.id, Delivery.status == "IN_TRANSIT"
    )).all())
    lines = [
        {
            "line_no": item.line_no,
            "product_name": item.product_name_snapshot,
            "remaining_quantity": item.order_quantity - item.received_quantity,
            "unit_id": item.unit_id,
        }
        for item in order.items
    ]
    return build_delivery_change_impact(
        po_no=order.po_no,
        order_status=str(order.status),
        previous=update.previous_date,
        expected=update.expected_date,
        required_date=_required_date(db, order),
        lines=lines,
        in_transit_deliveries=[
            {"delivery_no": row.delivery_no, "expected_arrival_date": _iso(row.expected_arrival_date),
             "status": row.status} for row in deliveries
        ],
        today=today,
    )


def _order_recipient_ids(db: Session, order) -> list[int]:
    """只提醒对这张订单有读取范围的人：采购员本人和授权采购经理。"""
    from app.modules.system.crud import get_user_role_codes
    from app.modules.system.data_scope import department_scope_snapshot, is_department_restricted
    from app.modules.system.model import Permission, Role, RolePermission, User, UserRole

    candidates = list(db.scalars(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            User.status == "ACTIVE",
            Role.status == "ACTIVE",
            Permission.permission_code == "procurement.orders.read",
        )
        .distinct()
    ).all())
    recipients: list[int] = []
    for candidate in candidates:
        roles = set(get_user_role_codes(db, candidate.id))
        if "SYS_ADMIN" in roles:
            recipients.append(candidate.id)
            continue
        if candidate.id != order.buyer_id and "PROCUREMENT_MANAGER" not in roles:
            continue
        if candidate.id == order.buyer_id:
            recipients.append(candidate.id)
            continue
        if order.department_id is not None and candidate.department_id != order.department_id:
            continue
        if is_department_restricted(db, candidate):
            allowed = set(department_scope_snapshot(db, candidate) or [])
            if order.department_id not in allowed:
                continue
        recipients.append(candidate.id)
    return sorted(set(recipients))


def _notify_delivery_change(db: Session, order, update, impact: dict[str, Any]) -> list:
    from app.modules.notifications.service import notify_users

    recipients = _order_recipient_ids(db, order)
    content = (
        f"订单 **{order.po_no}**：{impact['change_text']}。\n"
        f"当前订单状态 {order.status}；剩余未交 {impact['remaining_line_count']} 行；"
        f"在途到货 {impact['in_transit_count']} 条。\n"
        f"风险级别：{impact['risk_level']}。\n"
        "建议核对在途到货、申请期望日期与库存计划；如需要进一步分析，可在 AI 工作台继续查询该订单的到货与未交情况。"
    )
    if update.note:
        content += f"\n供应商说明：{update.note}"
    return notify_users(
        db,
        recipient_ids=recipients,
        notification_type="PURCHASE_ORDER_ETA_CHANGED",
        title=f"采购订单 {order.po_no} 预计交期变更",
        content=content,
        related_type="PURCHASE_ORDER",
        related_id=order.id,
    )


def record_delivery_change_event(db: Session, order, update, *, actor_id: int | None) -> AIBusinessEvent:
    """记录交期变更并按快速路径分派；调用方控制事务，事件与业务变更同事务提交。"""
    dedup_key = f"po-eta:{order.id}:{update.id}"
    existing = db.scalar(select(AIBusinessEvent).where(AIBusinessEvent.dedup_key == dedup_key))
    if existing is not None:
        return existing
    event = AIBusinessEvent(
        event_id=uuid4().hex,
        event_type=EVENT_PURCHASE_ORDER_ETA_CHANGED,
        subject_type=SUBJECT_PURCHASE_ORDER,
        subject_id=str(order.id),
        subject_version=update.id,
        dedup_key=dedup_key,
        source="supplier_portal",
        actor_id=actor_id,
        payload={
            "po_no": order.po_no,
            "previous_date": _iso(update.previous_date),
            "expected_date": _iso(update.expected_date),
            "note": update.note,
            "update_id": update.id,
        },
        triage_status="PENDING",
    )
    db.add(event)
    db.flush()
    return dispatch_delivery_change_event(db, event, order, update)


def dispatch_delivery_change_event(db: Session, event: AIBusinessEvent, order, update) -> AIBusinessEvent:
    """快速路径：类型、状态、变化幅度、权限和去重都由程序判定。"""
    today = date.today()
    if event.event_type not in FAST_PATH_EVENT_TYPES:
        event.triage_status = "SKIPPED"
        event.triage = {"stage": "FAST", "reason": "EVENT_TYPE_NOT_ENABLED"}
        return event
    if order.status not in ACTIVE_ORDER_STATUSES:
        event.triage_status = "SKIPPED"
        event.triage = {"stage": "FAST", "reason": "ORDER_NOT_ACTIVE"}
        return event
    if update.previous_date == update.expected_date:
        event.triage_status = "SKIPPED"
        event.triage = {"stage": "FAST", "reason": "NO_DATE_CHANGE"}
        return event

    impact = _order_impact(db, order, update, today)
    event.impact = impact
    task = None
    from app.modules.purchase_orders.delivery_tasks import record_change
    if impact["direction"] in {"DELAY", "EARLY", "INITIAL"}:
        task = record_change(db, order, update, assignee_id=order.buyer_id)
    notification_created = bool(_notify_delivery_change(db, order, update, impact))
    event.task_type = TASK_DELIVERY_CHANGE if task is not None else None
    event.task_id = task.id if task is not None else None
    event.triage_status = "DISPATCHED"
    event.triage = {
        "stage": "FAST",
        "verdict": "NOTIFY_AND_TASK" if task is not None else "NOTIFY",
        "risk_level": impact["risk_level"],
        "notification_created": notification_created,
        "analysis_mode": impact["analysis_mode"],
        "model_review_suggested": impact["risk_level"] == "HIGH" and impact["remaining_line_count"] > 0,
    }
    return event