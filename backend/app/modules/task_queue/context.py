"""Execution identity is inherited only by managed task processes."""

import os
from contextlib import contextmanager

from app.modules.task_queue import service


def identity():
    """读取托管任务的执行标识和隔离令牌；非任务进程返回 None。"""
    execution_id = os.environ.get("CHEMICALOPS_EXECUTION_ID")
    if not execution_id:
        return None
    return execution_id, int(os.environ["CHEMICALOPS_EXECUTION_TOKEN"])


def guard(db):
    """在托管任务中锁定并校验执行租约；普通进程不做校验。"""
    current = identity()
    return service.locked_execution(db, *current) if current else None


@contextmanager
def external_write():
    """在外部写入前后校验任务租约；外部操作本身不能由此回滚。"""
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
