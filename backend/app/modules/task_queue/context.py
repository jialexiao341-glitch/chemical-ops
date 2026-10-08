"""Execution identity is inherited only by managed task processes."""

import os
from contextlib import contextmanager

from app.modules.task_queue import service


def identity():
    execution_id = os.environ.get("CHEMICALOPS_EXECUTION_ID")
    if not execution_id:
        return None
    return execution_id, int(os.environ["CHEMICALOPS_EXECUTION_TOKEN"])


def guard(db):
    current = identity()
    return service.locked_execution(db, *current) if current else None


@contextmanager
def external_write():
    current = identity()
    if not current:
        yield
        return
    from app.core.db import SessionLocal
    with SessionLocal() as db:
        service.locked_execution(db, *current)
        yield
        service.locked_execution(db, *current)
        db.commit()
