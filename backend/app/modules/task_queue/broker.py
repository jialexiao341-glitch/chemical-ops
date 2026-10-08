"""AMQP topology and confirmed publishing; callers own database transactions."""

import json
from contextlib import asynccontextmanager

import aio_pika
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.core.config import Settings


class TaskMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    execution_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    delivery_generation: int = Field(ge=0)
    task_type: Literal["documents.fetch", "documents.ingest", "agent.run"]


@asynccontextmanager
async def connection(settings: Settings):
    client = await aio_pika.connect_robust(host=settings.rabbitmq_host, port=settings.rabbitmq_port,
        login=settings.rabbitmq_username, password=settings.rabbitmq_password,
        virtualhost=settings.rabbitmq_vhost, ssl=settings.rabbitmq_tls,
        timeout=10, heartbeat=30)
    try:
        yield client
    finally:
        await client.close()


async def topology(channel):
    exchange = await channel.declare_exchange("chemicalops.tasks", aio_pika.ExchangeType.DIRECT, durable=True)
    for route in ("documents", "agent", "documents.failed", "agent.failed"):
        queue = await channel.declare_queue(f"chemicalops.{route}", durable=True)
        await queue.bind(exchange, routing_key=route)
    return exchange


async def publish(exchange, *, message_id: str, body: TaskMessage, route: str):
    result = await exchange.publish(aio_pika.Message(
        body.model_dump_json().encode("utf-8"), message_id=message_id,
        content_type="application/json", delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    ), routing_key=route, mandatory=True)
    # Channel uses publisher_confirms and on_return_raises; negative confirms raise.
    if result is False:
        raise RuntimeError("Broker did not confirm publication")
