"""将 AI 文档知识库表迁移到已经存在的开发数据库。"""

import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    """执行 AI 文档知识库增量迁移；迁移脚本使用 IF NOT EXISTS，可重复执行。"""

    migration_path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "018_ai_documents.sql"
    statements = [statement.strip() for statement in migration_path.read_text(encoding="utf-8").split(";\n") if statement.strip()]
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    print("ai_documents_migration_ready=true")
    print("created_table_count=2")


if __name__ == "__main__":
    main()
