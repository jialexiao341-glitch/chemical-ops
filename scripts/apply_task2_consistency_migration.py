"""Apply the task-block-2 consistency constraints with a preflight check.

The preflight is intentionally fail-closed: existing duplicate active exceptions or
multiple acceptances for one delivery must be cleaned up before the unique indexes
are added. The script is safe to run repeatedly after the first successful run.
"""

from pathlib import Path
import sys

from sqlalchemy import inspect, text


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.db import engine  # noqa: E402


def _index_exists(connection, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(connection).get_indexes(table_name))


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspect(connection).get_columns(table_name))


def main() -> int:
    with engine.begin() as connection:
        duplicate_exceptions = connection.execute(
            text(
                """
                SELECT exception_type, source_type, source_id, COUNT(*) AS duplicate_count
                FROM operation_exceptions
                WHERE status IN ('OPEN', 'PROCESSING', 'RESOLVED')
                GROUP BY exception_type, source_type, source_id
                HAVING COUNT(*) > 1
                """
            )
        ).all()
        duplicate_acceptances = connection.execute(
            text(
                """
                SELECT delivery_id, COUNT(*) AS duplicate_count
                FROM quality_acceptances
                GROUP BY delivery_id
                HAVING COUNT(*) > 1
                """
            )
        ).all()
        if duplicate_exceptions or duplicate_acceptances:
            raise RuntimeError(
                "迁移前置检查失败：请先处理 operation_exceptions 未关闭重复记录 "
                f"({len(duplicate_exceptions)} 组) 和 quality_acceptances 重复到货单 "
                f"({len(duplicate_acceptances)} 组)，再重新执行本脚本。"
            )

        if not _column_exists(connection, "operation_exceptions", "active_dedupe_key"):
            connection.execute(
                text(
                    """
                    ALTER TABLE operation_exceptions
                    ADD COLUMN active_dedupe_key VARCHAR(200)
                    GENERATED ALWAYS (
                        CASE WHEN status IN ('OPEN', 'PROCESSING', 'RESOLVED')
                        THEN CONCAT(exception_type, ':', source_type, ':', source_id)
                        ELSE NULL END
                    ) STORED
                    """
                )
            )
        if not _index_exists(connection, "operation_exceptions", "uk_exception_active_dedupe"):
            connection.execute(text("ALTER TABLE operation_exceptions ADD UNIQUE KEY uk_exception_active_dedupe (active_dedupe_key)"))
        if not _index_exists(connection, "quality_acceptances", "uk_acceptance_delivery"):
            connection.execute(text("ALTER TABLE quality_acceptances ADD UNIQUE KEY uk_acceptance_delivery (delivery_id)"))

    print("task2_consistency_migration_ready=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
