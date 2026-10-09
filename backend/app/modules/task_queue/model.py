"""Persistent database queue state and retained legacy delivery history."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaskExecution(Base):
    __tablename__ = "async_task_executions"
    __table_args__ = (
        UniqueConstraint("task_type", "business_id", "run_generation", name="uq_task_business_generation"),
        Index("ix_task_status_lease", "status", "lease_until"),
        Index("ix_task_queue_poll", "task_type", "status", "created_at", "id"),
        Index("ix_task_actor", "actor_id"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32))
    business_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[int] = mapped_column(BigInteger)
    run_generation: Mapped[int] = mapped_column(Integer)
    business_revision: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    delivery_generation: Mapped[int] = mapped_column(Integer, default=0)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TaskOutbox(Base):
    """Legacy RabbitMQ delivery history; retained for inspection, never written by workers."""
    __tablename__ = "task_outbox"
    __table_args__ = (
        UniqueConstraint("execution_id", "delivery_generation", "routing_key", name="uq_task_outbox_delivery"),
        Index("ix_outbox_available", "status", "available_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("async_task_executions.id"))
    delivery_generation: Mapped[int] = mapped_column(Integer)
    routing_key: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    available_at: Mapped[datetime] = mapped_column(DateTime)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class TaskResourceLock(Base):
    __tablename__ = "task_resource_locks"
    resource_key: Mapped[str] = mapped_column(String(96), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("async_task_executions.id"))
