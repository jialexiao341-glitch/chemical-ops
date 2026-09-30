"""Saved analysis evidence and batch verification records."""

from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InsightSnapshot(Base):
    __tablename__ = "insight_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[int] = mapped_column(nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class RecallReportWorkflow(Base):
    __tablename__ = "recall_report_workflows"

    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    conclusion: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)


class RecallReportEvent(Base):
    __tablename__ = "recall_report_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    conclusion: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class BatchCheckItem(Base):
    __tablename__ = "batch_check_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "balance_id", name="uk_batch_check_balance"),
        UniqueConstraint("batch_id", "transaction_id", name="uk_batch_check_transaction"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    balance_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_balances.id"), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_transactions.id"), nullable=True)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    finding: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    checked_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class BatchCheckEvent(Base):
    __tablename__ = "batch_check_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("batch_check_items.id"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    finding: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class ExceptionActionDecision(Base):
    __tablename__ = "exception_action_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey("operation_exceptions.id"), nullable=False, unique=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("operation_tasks.id"), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class ExceptionActionEvent(Base):
    __tablename__ = "exception_action_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("exception_action_decisions.id"), nullable=False)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("operation_tasks.id"), nullable=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class FinanceDifferenceCheck(Base):
    __tablename__ = "finance_difference_checks"
    __table_args__ = (UniqueConstraint("order_id", "scope_key", name="uk_finance_check_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_label: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("insight_snapshots.id"), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    finding: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    checked_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class FinanceDifferenceEvent(Base):
    __tablename__ = "finance_difference_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("finance_difference_checks.id"), nullable=False)
    actor_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    finding: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
