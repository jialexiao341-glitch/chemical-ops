"""运行 ChemicalOps 后台定时任务。"""

import argparse
import logging
import time

import app.main  # noqa: F401
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.files.service import recover_stale_parses
from app.modules.jobs.service import scan_overdue_deliveries
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.scheduler")


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


def run_once_with_retry(*, max_attempts: int = 3, retry_delay_seconds: float = 5.0) -> dict[str, int]:
    """执行一轮扫描，失败时按配置重试，最后一次失败继续向上抛出。"""
    if max_attempts <= 0:
        raise ValueError("max_attempts 必须大于 0")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds 不能小于 0")

    for attempt in range(1, max_attempts + 1):
        try:
            return run_once()
        except Exception:
            if attempt >= max_attempts:
                raise
            LOGGER.warning("逾期扫描第 %s/%s 次尝试失败，将在 %.1f 秒后重试", attempt, max_attempts, retry_delay_seconds)
            time.sleep(retry_delay_seconds)

    raise RuntimeError("逾期扫描未返回结果")


def main() -> None:
    """按固定间隔循环执行任务；使用 --once 时只执行一轮。"""
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
    while True:
        try:
            LOGGER.info(
                "逾期扫描结果：%s",
                run_once_with_retry(max_attempts=args.max_attempts, retry_delay_seconds=args.retry_delay_seconds),
            )
        except Exception:
            LOGGER.exception("定时任务执行失败，下一轮继续")
        if args.once:
            return
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
