"""将文件附件关联表迁移到已经存在的开发数据库。"""

from pathlib import Path

from sqlalchemy import create_engine

from app.core.config import get_settings


def main() -> None:
    """执行可重复的文件附件增量迁移。"""

    path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "010_file_attachments.sql"
    statements = [statement.strip() for statement in path.read_text(encoding="utf-8").split(";\n") if statement.strip()]
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    print("file_attachment_migration_ready=true")
    print("created_table_count=1")


if __name__ == "__main__":
    main()
