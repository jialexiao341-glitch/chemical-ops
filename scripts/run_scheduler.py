"""运行 ChemicalOps 后台定时任务。"""

import argparse
from contextlib import contextmanager
import logging
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import app.main  # noqa: F401
from sqlalchemy import Connection, select, text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.observability import metrics
from app.core.production import production_config_errors
from app.modules.files.service import recover_stale_parses
from app.modules.jobs.service import (
    scan_overdue_deliveries,
    start_scheduled_run,
    update_scheduled_run,
)
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.scheduler")
SCHEDULER_LOCK_NAME = "chemicalops_scheduler_leader"


@contextmanager
def scheduler_leader_lock(*, wait: bool, poll_seconds: int) -> Iterator[Connection | None]:
    """通过 MySQL 会话级命名锁选出唯一调度器；连接断开后锁自动释放。"""

    if engine.dialect.name != "mysql":
        raise RuntimeError("多实例调度锁要求 MySQL 命名锁；当前数据库方言不受支持")
    connection = None
    while connection is None:
        candidate = engine.connect()
        try:
            acquired = candidate.execute(
                text("SELECT GET_LOCK(:lock_name, 0)"), {"lock_name": SCHEDULER_LOCK_NAME}
            ).scalar_one()
        except Exception:
            candidate.close()
            raise
        if acquired == 1:
            connection = candidate
            break
        candidate.close()
        if not wait:
            yield None
            return
        LOGGER.info("另一调度器持有主锁；等待其退出后接管")
        time.sleep(max(1, poll_seconds))
    try:
        yield connection
    finally:
        try:
            try:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": SCHEDULER_LOCK_NAME}
                )
                connection.commit()
            except Exception:
                LOGGER.warning("释放调度器主锁失败；数据库连接断开时锁由 MySQL 自动释放")
        finally:
            connection.close()


def run_once() -> dict[str, int]:
    """执行一轮逾期到货扫描，并在任务结束后关闭数据库会话。"""
    db = SessionLocal()
    try:
        actor = db.scalar(select(User).where(User.username == "system_admin", User.status == "ACTIVE"))
        if actor is None:
            raise RuntimeError("system_admin 不存在或已停用")
        result = scan_overdue_deliveries(db, actor)
        result["recovered_file_parse_count"] = recover_stale_parses(
            db,
            stale_after_seconds=get_settings().file_parse_stale_after_seconds,
        )
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_once_with_retry(
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 5.0,
    on_attempt: Callable[[int], None] | None = None,
) -> dict[str, int]:
    """执行一轮扫描，失败时按配置重试，最后一次失败继续向上抛出。"""
    if max_attempts <= 0:
        raise ValueError("max_attempts 必须大于 0")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds 不能小于 0")

    for attempt in range(1, max_attempts + 1):
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return run_once()
        except Exception:
            if attempt >= max_attempts:
                raise
            LOGGER.warning("逾期扫描第 %s/%s 次尝试失败，将在 %.1f 秒后重试", attempt, max_attempts, retry_delay_seconds)
            time.sleep(retry_delay_seconds)

    raise RuntimeError("逾期扫描未返回结果")


def run_once_with_history(*, max_attempts: int, retry_delay_seconds: float) -> dict[str, int]:
    """持久化一次逻辑运行及其重试次数、最终结果或失败类型。"""

    db = SessionLocal()
    run = start_scheduled_run(db, uuid4().hex)
    try:
        result = run_once_with_retry(
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            on_attempt=lambda attempt: update_scheduled_run(db, run, attempt_count=attempt),
        )
        update_scheduled_run(db, run, result=result)
        return result
    except Exception as exc:
        db.rollback()
        update_scheduled_run(db, run, error_type=type(exc).__name__)
        metrics.increment("scheduler_jobs", labels={"job": "overdue_scan", "status": "failure"})
        raise
    finally:
        db.close()


def main() -> None:
    """按固定间隔循环执行任务；使用 --once 时只执行一轮。"""
    config_errors = production_config_errors(get_settings())
    if config_errors:
        for error in config_errors:
            LOGGER.critical("生产配置校验失败：%s", error)
        raise SystemExit(f"生产配置校验失败，共 {len(config_errors)} 项；请查看启动日志")

    parser = argparse.ArgumentParser(description="ChemicalOps 定时任务执行器")
    parser.add_argument("--once", action="store_true", help="只执行一次后退出")
    parser.add_argument("--interval-seconds", type=int, default=get_settings().overdue_scan_interval_seconds, help="两次扫描之间的秒数")
    parser.add_argument("--max-attempts", type=int, default=3, help="每轮扫描失败后的最大尝试次数")
    parser.add_argument("--retry-delay-seconds", type=float, default=5.0, help="同一轮扫描重试之间的等待秒数")
    args = parser.parse_args()
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds 必须大于 0")
    if args.max_attempts <= 0:
        raise SystemExit("--max-attempts 必须大于 0")
    if args.retry_delay_seconds < 0:
        raise SystemExit("--retry-delay-seconds 不能小于 0")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with scheduler_leader_lock(wait=not args.once, poll_seconds=args.interval_seconds) as lock_connection:
        if lock_connection is None:
            LOGGER.info("本次单次执行未启动：已有调度器持有主锁")
            return
        LOGGER.info("已取得调度器主锁")
        while True:
            owns_lock = lock_connection.execute(
                text("SELECT IS_USED_LOCK(:lock_name) = CONNECTION_ID()"),
                {"lock_name": SCHEDULER_LOCK_NAME},
            ).scalar_one()
            if owns_lock != 1:
                raise RuntimeError("调度器主锁已丢失；停止执行以避免多实例重复调度")
            try:
                LOGGER.info(
                    "逾期扫描结果：%s",
                    run_once_with_history(max_attempts=args.max_attempts, retry_delay_seconds=args.retry_delay_seconds),
                )
            except Exception:
                LOGGER.exception("定时任务执行失败，下一轮继续")
            if args.once:
                return
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
