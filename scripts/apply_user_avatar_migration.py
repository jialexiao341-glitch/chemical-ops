"""为系统用户表增加头像二进制列。"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    """执行用户头像增量迁移（SHOW COLUMNS 守卫，可重复执行）。"""

    path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "019_user_avatar.sql"
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        columns = {row[0] for row in connection.execute(text("SHOW COLUMNS FROM sys_users"))}
        if "avatar" not in columns:
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
    print("user_avatar_migration_ready=true")


if __name__ == "__main__":
    main()
