"""交期变化业务待办；调用方须持有采购订单行锁并控制事务。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeliveryChangeTask(Base):
    __tablename__ = "delivery_change_tasks"
    __table_args__ = (UniqueConstraint("po_id", "active_slot", name="uq_delivery_change_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_update_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def record_change(db, order, update, *, assignee_id: int | None):
    """将实际变化合并到订单当前待办；不提交调用方事务。"""
    if update.previous_date == update.expected_date:
        return None
    task = db.scalar(select(DeliveryChangeTask).where(
        DeliveryChangeTask.po_id == order.id, DeliveryChangeTask.active_slot == 1
    ).with_for_update())
    if task is None:
        task = DeliveryChangeTask(po_id=order.id, assignee_id=assignee_id,
                                  latest_update_id=update.id, status="OPEN", active_slot=1)
        db.add(task)
    elif update.id > task.latest_update_id:
        task.latest_update_id = update.id
    db.flush()
    return task
