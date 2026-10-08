"""Publish persisted intents and report only safe task identifiers."""

import asyncio
import logging
from uuid import uuid4

from sqlalchemy import func, select

from app.modules.task_queue import broker, service
from app.modules.task_queue.model import TaskExecution, TaskOutbox

LOGGER = logging.getLogger("chemicalops.task_dispatcher")


def backlog(db) -> dict:
    counts = dict(db.execute(select(TaskOutbox.status, func.count()).group_by(TaskOutbox.status)).all())
    oldest = db.scalar(select(func.min(TaskOutbox.created_at)).where(TaskOutbox.status != "SENT"))
    return {"outbox": counts, "oldest_pending_seconds":
            max(0, (service.now() - oldest).total_seconds()) if oldest else 0}


async def dispatch_one(factory, exchange, owner: str) -> bool:
    def claim():
        with factory() as db:
            row = service.claim_delivery(db, owner)
            if row is None:
                return None
            execution = db.get(TaskExecution, row.execution_id)
            body = broker.TaskMessage(execution_id=execution.id,
                delivery_generation=row.delivery_generation, task_type=execution.task_type)
            return body, row.id, row.routing_key
    claimed = await asyncio.to_thread(claim)
    if claimed is None:
        return False
    body, message_id, route = claimed
    confirmed = False
    try:
        await broker.publish(exchange, message_id=message_id, body=body, route=route)
        confirmed = True
    except Exception as exc:
        # Never log exception text: connection exceptions can contain credentials.
        LOGGER.warning("publish_failed message_id=%s execution_id=%s error_type=%s",
                       message_id, body.execution_id, type(exc).__name__)
    def settle():
        with factory() as db:
            service.settle_delivery(db, message_id, owner, confirmed=confirmed)
    await asyncio.to_thread(settle)
    LOGGER.info("publication message_id=%s execution_id=%s confirmed=%s", message_id, body.execution_id, confirmed)
    return True


async def run(settings, factory, *, once: bool = False) -> None:
    owner = uuid4().hex
    while True:
        try:
            async with broker.connection(settings) as client:
                channel = await client.channel(publisher_confirms=True, on_return_raises=True)
                exchange = await broker.topology(channel)
                while True:
                    processed = await dispatch_one(factory, exchange, owner)
                    if once:
                        return
                    if not processed:
                        await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("dispatcher_unavailable error_type=%s", type(exc).__name__)
            if once:
                raise RuntimeError("Dispatcher unavailable; check database and broker configuration") from None
            await asyncio.sleep(5)
