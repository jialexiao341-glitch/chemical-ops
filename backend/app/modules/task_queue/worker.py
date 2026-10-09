"""Independent consumers with bounded execution and supervised process trees."""

import asyncio
import logging
import os
import socket
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.modules.task_queue import adapters, processes, service
from app.modules.task_queue.model import TaskExecution

LOGGER = logging.getLogger("chemicalops.task_worker")
ROOT = Path(__file__).resolve().parents[4]


async def database(factory, operation):
    """DB waits run outside the event loop so AMQP and sibling leases keep ticking."""
    def call():
        with factory() as db:
            return operation(db)
    return await asyncio.to_thread(call)


async def execute(factory, settings, execution):
    environment = os.environ.copy()
    for key, value in settings.model_dump().items():
        if value is not None:
            environment[key.upper()] = str(value).lower() if isinstance(value, bool) else str(value)
    environment.update(CHEMICALOPS_EXECUTION_ID=execution.id,
                       CHEMICALOPS_EXECUTION_TOKEN=str(execution.fencing_token),
                       CHEMICALOPS_WORKER_PID=str(os.getpid()))
    process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / "scripts/run_task_execution.py"),
        env=environment, cwd=ROOT, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=os.name != "nt")
    job = None
    try:
        if os.name == "nt":
            job = processes.WindowsJob(process.pid)
        def checkpoint(db):
            row = service.locked_execution(db, execution.id, execution.fencing_token)
            row.checkpoint = {**row.checkpoint, "process_pid": process.pid, "host": socket.gethostname()}
            db.commit()
        await database(factory, checkpoint)
        process.stdin.write(b"start\n")
        await process.stdin.drain()
        process.stdin.close()
        timeout = 3700 if execution.task_type.startswith("documents.") else settings.agent_task_timeout_seconds + 30
        deadline = asyncio.get_running_loop().time() + timeout
        while process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=settings.task_heartbeat_seconds)
            except TimeoutError:
                live = await database(factory, lambda db:
                    service.heartbeat(db, execution.id, execution.fencing_token, settings.task_lease_seconds))
                if not live:
                    raise service.ExecutionLost("Task cancelled or lease expired")
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("Execution exceeded runtime budget")
        def conclude(db):
            current = db.get(TaskExecution, execution.id)
            if current.status in service.TERMINAL or current.status == "RETRYING":
                return
            adapters.finish(db, execution.id, execution.fencing_token, status="FAILED",
                retryable=True, max_attempts=settings.task_max_attempts, error_code="WORKER_INTERRUPTED")
        await database(factory, conclude)
    finally:
        await processes.stop_process(process, job)


def recover(factory, settings):
    """Only re-run when a previous local process is demonstrably absent."""
    with factory() as db:
        rows = list(db.scalars(select(TaskExecution).where(TaskExecution.status == "RUNNING",
            TaskExecution.lease_until < service.now()).with_for_update(skip_locked=True)).all())
        for row in rows:
            checkpoint = row.checkpoint
            pid = checkpoint.get("process_pid")
            stopped = not pid or (checkpoint.get("host") == socket.gethostname() and not processes.process_alive(pid))
            row.fencing_token += 1
            row.lease_owner = None
            row.lease_until = None
            row.updated_at = service.now()
            if stopped and row.attempt_count < settings.task_max_attempts:
                row.status = "RETRYING"
                row.delivery_generation += 1
                row.next_attempt_at = service.now()
            else:
                row.status = "FAILED"
                row.error_code = "RECOVERY_ATTEMPTS_EXHAUSTED" if stopped else "RECOVERY_ISOLATION_REQUIRED"
                if stopped:
                    from sqlalchemy import delete
                    from app.modules.task_queue.model import TaskResourceLock
                    db.execute(delete(TaskResourceLock).where(TaskResourceLock.execution_id == row.id))
            adapters.apply_business_status(db, row)
        db.commit()
    return len(rows)


async def handle(factory, settings, execution):
    LOGGER.info("execution_started execution_id=%s token=%s attempt=%s",
                execution.id, execution.fencing_token, execution.attempt_count)
    try:
        await execute(factory, settings, execution)
    except service.ExecutionLost:
        pass  # Cancellation/recovery has changed authoritative state.
    except Exception as exc:
        LOGGER.warning("execution_interrupted execution_id=%s error_type=%s",
                       execution.id, type(exc).__name__)
        def fail(db):
            try:
                adapters.finish(db, execution.id, execution.fencing_token, status="FAILED", retryable=True,
                    max_attempts=settings.task_max_attempts, error_code="WORKER_INTERRUPTED")
            except service.ExecutionLost:
                db.rollback()
        await database(factory, fail)


async def run(settings, factory, queue, *, once=False):
    if queue not in service.TASK_ROUTES.values():
        raise ValueError("Unknown task queue")
    owner = uuid4().hex
    concurrency = settings.task_document_concurrency if queue == "documents" else settings.task_agent_concurrency
    running = set()
    recovery_at = 0
    try:
        while True:
            try:
                for task in list(running):
                    if task.done():
                        running.remove(task)
                        task.result()
                timestamp = asyncio.get_running_loop().time()
                if timestamp >= recovery_at:
                    await asyncio.to_thread(recover, factory, settings)
                    recovery_at = timestamp + settings.task_heartbeat_seconds
                if len(running) < concurrency:
                    execution = await database(factory, lambda db:
                        service.claim_next(db, queue, owner, settings.task_lease_seconds))
                    if once:
                        if execution is not None:
                            await handle(factory, settings, execution)
                        return
                    if execution is not None:
                        running.add(asyncio.create_task(handle(factory, settings, execution)))
                        continue
                # Polling remains asynchronous so running tasks can renew their leases.
                await asyncio.sleep(settings.task_poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("worker_unavailable error_type=%s", type(exc).__name__)
                if once:
                    raise RuntimeError("Worker unavailable; check task and database configuration") from None
                await asyncio.sleep(5)
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
