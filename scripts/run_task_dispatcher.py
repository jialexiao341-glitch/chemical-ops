"""Publish durable database task intents to RabbitMQ."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.production import production_config_errors
from app.modules.task_queue.dispatcher import backlog, run
from app.modules.task_queue.logging import configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings(_env_file=args.env_file)
    except Exception:
        raise SystemExit("Invalid configuration; check execution modes, credentials and lease settings") from None
    errors = production_config_errors(settings)
    if errors:
        raise SystemExit("; ".join(errors))
    if not settings.rabbitmq_username or not settings.rabbitmq_password:
        raise SystemExit("RabbitMQ credentials required")
    factory = sessionmaker(create_engine(settings.resolved_database_url, pool_pre_ping=True,
        hide_parameters=True, connect_args={"connect_timeout": 5, "read_timeout": 5, "write_timeout": 5}), expire_on_commit=False)
    configure(settings)
    if args.status:
        with factory() as db:
            print(json.dumps(backlog(db)))
    else:
        try:
            asyncio.run(run(settings, factory, once=args.once))
        except KeyboardInterrupt:
            pass
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
