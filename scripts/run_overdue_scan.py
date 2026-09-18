"""执行一次逾期到货扫描，供 Windows 任务计划或 CI 调度调用。"""

import app.main  # noqa: F401
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.jobs.service import scan_overdue_deliveries
from app.modules.system.model import User


def main() -> None:
    """使用系统管理员账号执行逾期扫描。"""
    db = SessionLocal()
    try:
        actor = db.scalar(select(User).where(User.username == "system_admin", User.status == "ACTIVE"))
        if actor is None:
            raise SystemExit("system_admin 不存在或已停用")
        print(scan_overdue_deliveries(db, actor))
    finally:
        db.close()


if __name__ == "__main__":
    main()
