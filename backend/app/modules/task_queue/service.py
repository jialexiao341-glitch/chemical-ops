"""Short database transactions for durable acceptance and delivery claims."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.modules.task_queue.model import TaskExecution, TaskOutbox, TaskResourceLock

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
    add_delivery(db, execution)
    db.flush()
    return execution


def add_delivery(db: Session, execution: TaskExecution, *, failed: bool = False,
                 available_at: datetime | None = None) -> TaskOutbox:
    row = TaskOutbox(id=uuid4().hex, execution_id=execution.id,
        delivery_generation=execution.delivery_generation,
        routing_key=TASK_ROUTES[execution.task_type] + (".failed" if failed else ""),
        status="PENDING", available_at=available_at or now(), attempt_count=0, created_at=now())
    db.add(row)
    return row


def claim_delivery(db: Session, owner: str, lease_seconds: int = 60) -> TaskOutbox | None:
    timestamp = now()
    row = db.scalar(select(TaskOutbox).where(TaskOutbox.available_at <= timestamp,
        or_(TaskOutbox.status == "PENDING",
            (TaskOutbox.status == "PUBLISHING") & (TaskOutbox.lease_until < timestamp)))
        .order_by(TaskOutbox.available_at, TaskOutbox.id).with_for_update(skip_locked=True).limit(1))
    if row is None:
        db.commit()
        return None
    row.status, row.lease_owner = "PUBLISHING", owner
    row.lease_until = timestamp + timedelta(seconds=lease_seconds)
    row.attempt_count += 1
    db.commit()
    return row


def settle_delivery(db: Session, message_id: str, owner: str, *, confirmed: bool) -> None:
    db.execute(update(TaskOutbox).where(TaskOutbox.id == message_id,
        TaskOutbox.status == "PUBLISHING", TaskOutbox.lease_owner == owner).values(
        status="SENT" if confirmed else "PENDING", lease_owner=None, lease_until=None,
        available_at=now() + timedelta(seconds=0 if confirmed else 5)))
    db.commit()


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
        add_delivery(db, execution, available_at=execution.next_attempt_at)
    else:
        if status not in TERMINAL:
            raise ValueError("Invalid final status")
        execution.status = status
        db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id == execution_id))
        if status == "FAILED":
            add_delivery(db, execution, failed=True)
    execution.lease_owner = None
    execution.lease_until = None
    execution.updated_at = now()
    # Caller commits the business outcome and execution result together.
    return execution
