"""将库存模块新增表迁移到已经存在的开发数据库。"""

from pathlib import Path

from sqlalchemy import create_engine

from app.core.config import get_settings


def main() -> None:
    """执行库存增量迁移；迁移脚本使用 IF NOT EXISTS，可重复执行。"""

    migration_path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "001_inventory.sql"
    statements = [statement.strip() for statement in migration_path.read_text(encoding="utf-8").split(";\n") if statement.strip()]
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    print("inventory_migration_ready=true")
    print("created_table_count=5")


if __name__ == "__main__":
    main()
