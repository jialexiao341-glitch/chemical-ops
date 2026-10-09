"""Short database transactions for durable acceptance and worker claims."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.modules.task_queue.model import TaskExecution, TaskResourceLock

TASK_ROUTES = {"documents.fetch": "documents", "documents.ingest": "documents", "agent.run": "agent"}
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "WAITING_INPUT"}


def now() -> datetime:
    value = datetime.now(timezone.utc).replace(tzinfo=None)
    # Match MySQL DATETIME(3) precision so a freshly accepted intent is due immediately.
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def enqueue(db: Session, *, task_type: str, business_id: str, actor_id: int,
            generation: int, payload: dict, revision: int = 0,
            resource_key: str | None = None) -> TaskExecution:
    """Caller owns the transaction containing both business state and this intent."""
    if task_type not in TASK_ROUTES:
        raise ValueError("Unknown task type")
    timestamp = now()
    execution = TaskExecution(id=uuid4().hex, task_type=task_type, business_id=business_id,
        actor_id=actor_id, run_generation=generation, business_revision=revision,
        payload=payload, checkpoint={}, status="QUEUED", attempt_count=0,
        delivery_generation=0, fencing_token=0, created_at=timestamp, updated_at=timestamp)
    db.add(execution)
    db.flush()
    if resource_key:
        db.add(TaskResourceLock(resource_key=resource_key, execution_id=execution.id))
    db.flush()
    return execution


def claim_next(db: Session, queue: str, owner: str, lease_seconds: int) -> TaskExecution | None:
    """Lock and claim one due task atomically; competing workers skip locked rows."""
    task_types = [task_type for task_type, route in TASK_ROUTES.items() if route == queue]
    if not task_types:
        raise ValueError("Unknown task queue")
    timestamp = now()
    execution = db.scalar(select(TaskExecution).where(
        TaskExecution.task_type.in_(task_types),
        TaskExecution.status.in_(("QUEUED", "RETRYING")),
        or_(TaskExecution.next_attempt_at.is_(None), TaskExecution.next_attempt_at <= timestamp))
        .order_by(TaskExecution.created_at, TaskExecution.id)
        .with_for_update(skip_locked=True).limit(1))
    if execution is None:
        db.commit()
        return None
    return claim_execution(db, execution.id, execution.delivery_generation, owner, lease_seconds)


def claim_execution(db: Session, execution_id: str, delivery_generation: int,
                    owner: str, lease_seconds: int) -> TaskExecution | None:
    timestamp = now()
    count = db.execute(update(TaskExecution).where(TaskExecution.id == execution_id,
        TaskExecution.delivery_generation == delivery_generation,
        TaskExecution.status.in_(("QUEUED", "RETRYING")),
        or_(TaskExecution.next_attempt_at.is_(None), TaskExecution.next_attempt_at <= timestamp))
        .values(status="RUNNING", lease_owner=owner,
        fencing_token=TaskExecution.fencing_token + 1,
        attempt_count=TaskExecution.attempt_count + 1,
        lease_until=timestamp + timedelta(seconds=lease_seconds),
        heartbeat_at=timestamp, updated_at=timestamp).execution_options(synchronize_session=False)).rowcount
    db.commit()
    if count != 1:
        return None
    return db.get(TaskExecution, execution_id, populate_existing=True)


class ExecutionLost(RuntimeError):
    pass


def locked_execution(db: Session, execution_id: str, token: int) -> TaskExecution:
    execution = db.scalar(select(TaskExecution).where(TaskExecution.id == execution_id)
        .with_for_update().execution_options(populate_existing=True))
    if execution is None or execution.status != "RUNNING" or execution.fencing_token != token \
            or execution.lease_until is None or execution.lease_until <= now():
        raise ExecutionLost("Execution no longer owns its lease")
    return execution


def heartbeat(db: Session, execution_id: str, token: int, seconds: int) -> bool:
    timestamp = now()
    count = db.execute(update(TaskExecution).where(TaskExecution.id == execution_id,
        TaskExecution.fencing_token == token, TaskExecution.status == "RUNNING",
        TaskExecution.lease_until > timestamp).values(
        heartbeat_at=timestamp, lease_until=timestamp + timedelta(seconds=seconds))) .rowcount
    db.commit()
    return count == 1


def finish(db: Session, execution_id: str, token: int, *, status: str,
           retryable: bool = False, max_attempts: int = 3, error_code: str | None = None) -> TaskExecution:
    execution = locked_execution(db, execution_id, token)
    execution.error_code = error_code
    if status == "FAILED" and retryable and execution.attempt_count < max_attempts:
        execution.status = "RETRYING"
        execution.delivery_generation += 1
        execution.next_attempt_at = now() + timedelta(seconds=30 if execution.attempt_count == 1 else 120)
    else:
        if status not in TERMINAL:
            raise ValueError("Invalid final status")
        execution.status = status
        db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id == execution_id))
    execution.lease_owner = None
    execution.lease_until = None
    execution.updated_at = now()
    # Caller commits the business outcome and execution result together.
    return execution
