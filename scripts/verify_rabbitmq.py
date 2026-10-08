"""Verify the isolated RabbitMQ deployment without accessing business queues."""

import argparse
import asyncio
from pathlib import Path

import aio_pika
import httpx


async def verify(action: str) -> None:
    values = dict(line.split("=", 1) for line in
                  (Path(__file__).resolve().parents[1] / ".env.rabbitmq").read_text().splitlines()
                  if line and not line.startswith("#"))
    user, password = values["RABBITMQ_USERNAME"], values["RABBITMQ_PASSWORD"]
    port = int(values.get("RABBITMQ_PORT", "5672"))
    management_port = int(values.get("RABBITMQ_MANAGEMENT_PORT", "15672"))
    with httpx.Client(auth=(user, password), timeout=10) as client:
        response = client.get(f"http://127.0.0.1:{management_port}/api/overview")
        response.raise_for_status()
    connection = await aio_pika.connect(host="127.0.0.1", port=port, login=user,
                                       password=password, virtualhost="chemicalops")
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        queue = await channel.declare_queue("chemicalops.verification.persistence", durable=True)
        if action == "publish":
            await channel.default_exchange.publish(
                aio_pika.Message(b"persistence-check", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=queue.name, mandatory=True,
            )
            print("Management authenticated; persistent message confirmed")
        else:
            message = await queue.get(timeout=10)
            assert message.body == b"persistence-check"
            await message.ack()
            await queue.delete(if_unused=True, if_empty=True)
            print("Persistent message recovered and acknowledged; verification queue removed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["publish", "consume"])
    asyncio.run(verify(parser.parse_args().action))
