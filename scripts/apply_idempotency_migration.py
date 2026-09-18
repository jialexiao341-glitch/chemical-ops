"""将统一幂等请求表迁移到开发数据库。"""

from pathlib import Path

from sqlalchemy import create_engine

from app.core.config import get_settings


def main() -> None:
    """执行可重复的幂等表迁移。"""
    path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "012_idempotency.sql"
    statements = [statement.strip() for statement in path.read_text(encoding="utf-8").split(";\n") if statement.strip()]
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    print("idempotency_migration_ready=true")
    print("created_table_count=1")


if __name__ == "__main__":
    main()
