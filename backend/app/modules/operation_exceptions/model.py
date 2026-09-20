"""采购运营异常和处理任务的数据模型。"""

from datetime import datetime

from sqlalchemy import Computed, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.modules.system.file_model import SysFile


class OperationException(Base):
    """采购流程中的异常记录。"""

    __tablename__ = "operation_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    exception_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(nullable=False)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), nullable=True)
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    delivery_item_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_items.id"), nullable=True)
    responsible_department_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    closing_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    active_dedupe_key: Mapped[str | None] = mapped_column(String(200), Computed("CASE WHEN status IN ('OPEN', 'PROCESSING', 'RESOLVED') THEN CONCAT(exception_type, ':' , source_type, ':' , source_id) ELSE NULL END", persisted=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    tasks: Mapped[list["OperationTask"]] = relationship(
        back_populates="exception", cascade="all, delete-orphan", order_by="OperationTask.id"
    )


class OperationTask(Base):
    """异常处理任务。"""

    __tablename__ = "operation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey("operation_exceptions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    due_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completion_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    exception: Mapped[OperationException] = relationship(back_populates="tasks")
    comments: Mapped[list["OperationTaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="OperationTaskComment.id"
    )


class OperationTaskComment(Base):
    """异常任务处理记录。"""

    __tablename__ = "operation_task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("operation_tasks.id"), nullable=False)
    commenter_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_file_id: Mapped[int | None] = mapped_column(ForeignKey("sys_files.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))

    task: Mapped[OperationTask] = relationship(back_populates="comments")
