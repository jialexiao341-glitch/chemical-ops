"""后台任务运行历史的数据模型。"""

from datetime import datetime

from sqlalchemy import Index, JSON, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SchedulerJobRun(Base):
    """持久记录每次调度任务的状态、重试次数和结果摘要。"""

    __tablename__ = "scheduler_job_runs"
    __table_args__ = (
        Index("idx_scheduler_job_run_task_started", "task_name", "started_at"),
        Index("idx_scheduler_job_run_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    task_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
