"""Apply ordered, checksummed MySQL migrations with a persistent ledger."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from sqlalchemy import inspect, text
from sqlalchemy.dialects import mysql


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.core.production import production_config_errors  # noqa: E402


MIGRATIONS_DIR = ROOT / "database" / "migrations"
MIGRATION_LOCK = "chemicalops_schema_migrations"
LEDGER_TABLE = "schema_migrations"
ATTEMPT_TABLE = "schema_migration_attempts"
CORE_TABLES = {"sys_users", "md_products", "suppliers", "deliveries", "purchase_orders"}
# 056 was applied before its freight CHECK constraint was added to the file.
# 057 installs that constraint and re-baselines only this known ledger entry.
MIGRATION_CHECKSUM_REPAIRS = {
    "056": {
        "ledger_checksum": "6661e70d6d3b52534087fcc0cafb4d5226b0a16dc60f3528a39c0333e25c0933",
        "file_checksum": "8e851b0be5cdd75eae85deb28c3c4373fd2e0821f72fd144071579515ad72b6f",
        "repair_version": "057",
    },
}


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str


def _migration_files() -> list[Migration]:
    files: list[Migration] = []
    pattern = re.compile(r"^(\d{3})_(.+)\.sql$")
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = pattern.fullmatch(path.name)
        if not match:
            raise RuntimeError(f"不符合 NNN_name.sql 命名规则的迁移文件：{path.name}")
        # Normalize line endings so Windows and Linux checkouts produce the same ledger checksum.
        raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        files.append(
            Migration(
                version=match.group(1),
                name=match.group(2),
                path=path,
                checksum=hashlib.sha256(raw).hexdigest(),
            )
        )
    versions = [int(migration.version) for migration in files]
    if not files or versions[0] != 1 or versions != list(range(1, versions[-1] + 1)):
        raise RuntimeError("迁移版本号必须连续；发现缺号或迁移目录为空")
    return files


def _ensure_ledger(connection) -> None:
    connection.exec_driver_sql(
        f"""CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
            version VARCHAR(32) NOT NULL,
            name VARCHAR(128) NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at DATETIME(3) NOT NULL,
            duration_ms BIGINT UNSIGNED NOT NULL,
            applied_by VARCHAR(128) NOT NULL,
            PRIMARY KEY (version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已成功应用的数据库迁移'"""
    )
    connection.exec_driver_sql(
        f"""CREATE TABLE IF NOT EXISTS {ATTEMPT_TABLE} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            version VARCHAR(32) NOT NULL,
            checksum CHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL,
            started_at DATETIME(3) NOT NULL,
            finished_at DATETIME(3) NULL,
            duration_ms BIGINT UNSIGNED NULL,
            error_summary VARCHAR(2000) NULL,
            PRIMARY KEY (id),
            KEY idx_schema_migration_attempt_version (version, started_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据库迁移执行记录'"""
    )
    connection.commit()


def _table_exists(connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspect(connection).get_columns(table_name))


def _index_exists(connection, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(connection).get_indexes(table_name))


def _require_core_schema(connection) -> None:
    existing = set(inspect(connection).get_table_names())
    missing = sorted(CORE_TABLES - existing)
    if missing:
        raise RuntimeError(
            "基础数据库结构不完整；先对空库运行 scripts/init_database.py，缺少："
            + ", ".join(missing)
        )


def _execute_sql_file(connection, migration: Migration) -> None:
    source = migration.path.read_text(encoding="utf-8")
    for statement in source.split(";"):
        sql = statement.strip()
        if sql:
            connection.exec_driver_sql(sql)
            # MySQL DDL implicitly commits. Explicitly clear SQLAlchemy's transaction
            # state after every statement so a partial migration can be resumed.
            connection.commit()


def _apply_finance_ref(connection, migration: Migration) -> None:
    table = "finance_payments"
    if not _table_exists(connection, table):
        raise RuntimeError("finance_payments 表不存在，无法执行付款流水号迁移")
    if not _column_exists(connection, table, "transaction_ref"):
        raise RuntimeError("finance_payments.transaction_ref 列不存在，无法执行付款流水号迁移")
    if _index_exists(connection, table, "uk_finance_payment_transaction_ref"):
        return
    duplicates = connection.execute(
        text(
            "SELECT transaction_ref FROM finance_payments "
            "WHERE transaction_ref IS NOT NULL GROUP BY transaction_ref HAVING COUNT(*) > 1 LIMIT 10"
        )
    ).all()
    if duplicates:
        raise RuntimeError(
            "付款流水号唯一索引迁移预检失败：存在重复 transaction_ref；"
            "请先导出并人工核对重复付款记录"
        )
    _execute_sql_file(connection, migration)


def _apply_task2_consistency(connection, migration: Migration) -> None:
    exception_table = "operation_exceptions"
    acceptance_table = "quality_acceptances"
    if not _table_exists(connection, exception_table) or not _table_exists(connection, acceptance_table):
        raise RuntimeError("运营异常或质量验收表不存在，无法执行一致性迁移")

    acceptance_index_exists = _index_exists(connection, acceptance_table, "uk_acceptance_delivery")
    duplicate_acceptances = connection.execute(
        text(
            "SELECT delivery_id FROM quality_acceptances "
            "GROUP BY delivery_id HAVING COUNT(*) > 1 LIMIT 10"
        )
    ).all()
    if duplicate_acceptances and not acceptance_index_exists:
        raise RuntimeError(
            "一致性迁移预检失败：存在同一到货单多条质量验收；"
            "为避免丢失验收及明细历史，请先核对这些记录"
        )

    # The SQL file contains the auditable data cleanup as well as the DDL.
    # Recheck DDL state per statement so a retry after MySQL's implicit DDL
    # commit can safely resume without repeating or losing the cleanup.
    statements = [statement.strip() for statement in migration.path.read_text(encoding="utf-8").split(";")]
    for statement in statements:
        sql = statement.strip()
        if not sql:
            continue
        normalized = " ".join(sql.upper().split())
        if normalized.startswith("ALTER TABLE OPERATION_EXCEPTIONS"):
            if "ADD COLUMN ACTIVE_DEDUPE_KEY" in normalized and _column_exists(
                connection, exception_table, "active_dedupe_key"
            ):
                continue
            if "ADD UNIQUE KEY UK_EXCEPTION_ACTIVE_DEDUPE" in normalized and _index_exists(
                connection, exception_table, "uk_exception_active_dedupe"
            ):
                continue
        if normalized.startswith("ALTER TABLE QUALITY_ACCEPTANCES") and _index_exists(
            connection, acceptance_table, "uk_acceptance_delivery"
        ):
            continue
        connection.exec_driver_sql(sql)
        connection.commit()


def _apply_user_avatar(connection) -> None:
    if not _table_exists(connection, "sys_users"):
        raise RuntimeError("sys_users 表不存在，无法执行头像迁移")
    if not _column_exists(connection, "sys_users", "avatar"):
        connection.exec_driver_sql("ALTER TABLE sys_users ADD COLUMN avatar MEDIUMBLOB NULL")
        connection.commit()


def _apply_auth_security(connection) -> None:
    """Apply the auth migration safely if DDL was interrupted after ALTER TABLE."""

    if not _table_exists(connection, "sys_users"):
        raise RuntimeError("sys_users 表不存在，无法执行登录安全迁移")
    if not _column_exists(connection, "sys_users", "token_version"):
        connection.exec_driver_sql(
            "ALTER TABLE sys_users ADD COLUMN token_version INT UNSIGNED NOT NULL DEFAULT 0"
        )
        connection.commit()
    connection.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS sys_login_attempts (
            scope_key CHAR(64) NOT NULL COMMENT '登录限速范围的 SHA-256 指纹',
            failure_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
            window_started_at DATETIME(3) NOT NULL,
            locked_until DATETIME(3) NULL,
            updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                ON UPDATE CURRENT_TIMESTAMP(3),
            PRIMARY KEY (scope_key),
            KEY idx_login_attempt_updated (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录失败限速记录'"""
    )
    connection.commit()


def _apply_idempotency_response_headers(connection) -> None:
    if not _table_exists(connection, "sys_idempotency_records"):
        raise RuntimeError("sys_idempotency_records 表不存在，无法升级幂等响应头字段")
    if not _column_exists(connection, "sys_idempotency_records", "response_headers"):
        connection.exec_driver_sql(
            "ALTER TABLE sys_idempotency_records ADD COLUMN response_headers JSON NULL"
        )
        connection.commit()


def _apply_ai_conversation_pinned(connection, migration: Migration) -> None:
    """Apply 025 to legacy schemas and validate the column in newer baselines."""
    table = "ai_conversations"
    if not _table_exists(connection, table):
        raise RuntimeError("ai_conversations 表不存在，无法执行会话置顶迁移")

    column = next(
        (item for item in inspect(connection).get_columns(table) if item["name"] == "pinned"),
        None,
    )
    if column is None:
        _execute_sql_file(connection, migration)
        return

    data_type = column["type"].compile(dialect=mysql.dialect()).upper()
    default = str(column.get("default") or "").strip().strip("'").strip('"').strip("() ")
    if data_type != "TINYINT(1)" or column["nullable"] or default != "0":
        raise RuntimeError(
            "Schema conflict: ai_conversations.pinned exists with a definition "
            "that differs from migration 025; "
            f"type={data_type}, default={column.get('default')!r}, "
            f"nullable={column['nullable']}. Reconcile the schema before migrating."
        )


def _apply_return_reconciliation_items(connection, migration: Migration) -> None:
    """恢复中断的增量迁移；每个 ALTER 在 MySQL 中作为一个原子 DDL。"""
    statements = [part.strip() for part in migration.path.read_text(encoding="utf-8").split(";") if part.strip()]
    for sql in statements:
        if sql.startswith("ALTER TABLE inventory_return_items") and _column_exists(connection, "inventory_return_items", "source_delivery_item_id"):
            continue
        if sql.startswith("ALTER TABLE finance_reconciliations") and _column_exists(connection, "finance_reconciliations", "items_version"):
            continue
        if sql.startswith("ALTER TABLE finance_settlements"):
            checks = inspect(connection).get_check_constraints("finance_settlements")
            if any(check["name"] == "chk_finance_settlement_amount" and ">=" in check["sqltext"] for check in checks):
                continue
        connection.exec_driver_sql(sql)
        connection.commit()


def _apply_migration(connection, migration: Migration) -> None:
    if migration.version == "025":
        _apply_ai_conversation_pinned(connection, migration)
    elif migration.version == "014":
        _apply_finance_ref(connection, migration)
    elif migration.version == "016":
        _apply_task2_consistency(connection, migration)
    elif migration.version == "019":
        _apply_user_avatar(connection)
    elif migration.version == "021":
        _apply_auth_security(connection)
    elif migration.version == "022":
        _apply_idempotency_response_headers(connection)
    elif migration.version == "024":
        if not _column_exists(connection, "md_products", "safety_stock_quantity"):
            connection.exec_driver_sql("ALTER TABLE md_products ADD COLUMN safety_stock_quantity DECIMAL(18,6) NULL COMMENT '安全库存阈值，单位沿用产品计量单位' AFTER unit_id")
            connection.commit()
        if not _index_exists(connection, "md_products", "idx_product_safety_stock"):
            connection.exec_driver_sql("ALTER TABLE md_products ADD KEY idx_product_safety_stock (status, safety_stock_quantity)")
            connection.commit()
    elif migration.version == "034":
        _apply_return_reconciliation_items(connection, migration)
    elif migration.version == "053":
        _apply_purchase_order_source_guard(connection, migration)
    elif migration.version == "057":
        _apply_rfq_total_cost_repair(connection)
    elif migration.version == "066":
        # 授权回填依赖临时表识别原本未配置的账号；所有数据修改必须同一事务提交。
        for statement in migration.path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement.strip())
        connection.commit()
    else:
        _execute_sql_file(connection, migration)


def _apply_rfq_total_cost_repair(connection) -> None:
    """Apply the missing 056 constraint, then reconcile its known checksum drift."""
    required_columns = {
        "supplier_quote_items": {"freight_amount", "freight_tax_rate", "freight_tax_included"},
        "quote_comparison_items": {"freight_amount", "freight_tax_rate", "freight_tax_included", "analysis_json"},
    }
    for table, columns in required_columns.items():
        missing = sorted(column for column in columns if not _column_exists(connection, table, column))
        if missing:
            raise RuntimeError(f"迁移 056 的结构未完整应用，{table} 缺少列：" + ", ".join(missing))

    constraint = connection.execute(
        text(
            "SELECT cc.CHECK_CLAUSE FROM information_schema.TABLE_CONSTRAINTS tc "
            "JOIN information_schema.CHECK_CONSTRAINTS cc "
            "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_SCHEMA = DATABASE() AND tc.TABLE_NAME = 'supplier_quote_items' "
            "AND tc.CONSTRAINT_NAME = 'chk_quote_item_freight'"
        )
    ).scalar()
    if constraint is None:
        connection.exec_driver_sql(
            "ALTER TABLE supplier_quote_items ADD CONSTRAINT chk_quote_item_freight CHECK ("
            "(freight_amount IS NULL OR freight_amount >= 0) AND "
            "(freight_tax_rate IS NULL OR freight_tax_rate BETWEEN 0 AND 100))"
        )
        connection.commit()
    else:
        normalized = " ".join(str(constraint).lower().replace("`", "").split())
        if not all(token in normalized for token in ("freight_amount", ">= 0", "freight_tax_rate", "between 0 and 100")):
            raise RuntimeError("chk_quote_item_freight 已存在但定义不匹配；停止迁移以保留现有约束")

    repair = MIGRATION_CHECKSUM_REPAIRS["056"]
    result = connection.execute(
        text(
            f"UPDATE {LEDGER_TABLE} SET checksum = :file_checksum "
            "WHERE version = '056' AND name = 'rfq_total_cost_analysis' AND checksum = :ledger_checksum"
        ),
        {"file_checksum": repair["file_checksum"], "ledger_checksum": repair["ledger_checksum"]},
    )
    if result.rowcount != 1:
        current = connection.execute(
            text(f"SELECT checksum FROM {LEDGER_TABLE} WHERE version = '056' AND name = 'rfq_total_cost_analysis'")
        ).scalar()
        if current != repair["file_checksum"]:
            raise RuntimeError("迁移 056 台账校验和与预期修复源不符；停止迁移")
    connection.commit()


def _apply_purchase_order_source_guard(connection, migration: Migration) -> None:
    """恢复中断 DDL；唯一键已存在时不再扩大历史例外集合。"""
    indexes = inspect(connection).get_indexes("purchase_orders")
    if any(index["name"] == "uk_purchase_order_comparison" and index.get("column_names") == ["source_comparison_guard"] for index in indexes):
        return
    statements = [part.strip() for part in migration.path.read_text(encoding="utf-8").split(";") if part.strip()]
    for sql in statements:
        normalized = " ".join(sql.upper().split())
        if normalized.startswith("ALTER TABLE PURCHASE_ORDERS"):
            if "ADD COLUMN LEGACY_SOURCE_DUPLICATE" in normalized and _column_exists(
                connection, "purchase_orders", "legacy_source_duplicate"
            ):
                continue
            if "ADD COLUMN SOURCE_COMPARISON_GUARD" in normalized and _column_exists(
                connection, "purchase_orders", "source_comparison_guard"
            ):
                continue
            if "ADD UNIQUE KEY UK_PURCHASE_ORDER_COMPARISON" in normalized:
                existing = next((index for index in indexes
                                 if index["name"] == "uk_purchase_order_comparison"), None)
                if existing and existing.get("column_names") == ["source_comparison_guard"]:
                    continue
                if existing:
                    raise RuntimeError(
                        "采购订单来源索引名称已占用且列不匹配；停止迁移以保留现有约束，需人工核对"
                    )
        connection.exec_driver_sql(sql)
        connection.commit()


def _run_backup() -> str:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(BACKEND), existing_pythonpath) if value
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup_mysql.py")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "迁移前数据库备份失败；未执行任何迁移。"
            + (f" {result.stderr.strip()[-1000:]}" if result.stderr.strip() else "")
        )
    backup_line = next(
        (line.strip() for line in reversed(result.stdout.splitlines()) if line.strip().startswith("mysql_backup=")),
        None,
    )
    if backup_line is None:
        raise RuntimeError("备份命令未返回备份文件路径；未执行任何迁移")
    backup_path = Path(backup_line.partition("=")[2]).expanduser()
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise RuntimeError(f"迁移前备份文件不存在或为空；未执行任何迁移：{backup_path}")
    return backup_line


def _latest_applied(connection) -> dict[str, dict[str, str]]:
    if not _table_exists(connection, LEDGER_TABLE):
        return {}
    rows = connection.execute(
        text(f"SELECT version, name, checksum, applied_at FROM {LEDGER_TABLE} ORDER BY version")
    ).mappings()
    return {row["version"]: dict(row) for row in rows}


def status() -> int:
    migrations = _migration_files()
    with engine.connect() as connection:
        existing_tables = set(inspect(connection).get_table_names())
        applied = _latest_applied(connection) if LEDGER_TABLE in existing_tables else {}
        _validate_ledger_state(migrations, applied)
        for migration in migrations:
            row = applied.get(migration.version)
            if row is None:
                state = "PENDING"
            elif row["checksum"] != migration.checksum:
                repair = _checksum_repair_for(migration, row, migrations, applied)
                state = f"CHECKSUM_REPAIR_PENDING {repair['repair_version']}" if repair else "CHECKSUM_MISMATCH"
            else:
                state = f"APPLIED {row['applied_at']}"
            print(f"{migration.version} {migration.name} {state}")
        attempts = set(existing_tables) & {ATTEMPT_TABLE}
        if attempts:
            rows = connection.execute(
                text(
                    f"SELECT version, status, started_at, error_summary FROM {ATTEMPT_TABLE} "
                    "WHERE status <> 'APPLIED' ORDER BY id DESC LIMIT 20"
                )
            ).all()
            for version, state, started_at, error in rows:
                print(f"ATTEMPT {version} {state} {started_at} {error or ''}".rstrip())
    return 0


def _validate_ledger_state(migrations: list[Migration], applied: dict[str, dict[str, str]]) -> None:
    known_versions = {migration.version for migration in migrations}
    unknown = sorted(set(applied) - known_versions)
    if unknown:
        raise RuntimeError("迁移台账包含仓库中不存在的版本：" + ", ".join(unknown))
    applied_versions = sorted(int(version) for version in applied)
    if applied_versions and applied_versions != list(range(1, applied_versions[-1] + 1)):
        raise RuntimeError("迁移台账版本不连续；请先人工核对数据库结构和迁移记录")


def _checksum_repair_for(migration: Migration, row: dict[str, str], migrations: list[Migration], applied: dict[str, dict[str, str]]) -> dict | None:
    repair = MIGRATION_CHECKSUM_REPAIRS.get(migration.version)
    if repair is None or repair["ledger_checksum"] != row["checksum"] or repair["file_checksum"] != migration.checksum:
        return None
    repair_migration = next((item for item in migrations if item.version == repair["repair_version"]), None)
    if repair_migration is None or repair["repair_version"] in applied:
        return None
    return repair


def upgrade_database(
    *, target_version: str | None = None, no_backup: bool = False, fresh_database_bootstrap: bool = False
) -> int:
    settings = get_settings()
    config_errors = production_config_errors(settings)
    if config_errors:
        raise RuntimeError("生产配置校验失败：" + "；".join(config_errors))
    if no_backup and settings.app_env.strip().lower() in {"prod", "production"} and not fresh_database_bootstrap:
        raise RuntimeError("生产环境不允许跳过迁移前备份")

    all_migrations = _migration_files()
    migrations = all_migrations
    if target_version is not None:
        if target_version not in {migration.version for migration in migrations}:
            raise ValueError(f"未知迁移目标版本：{target_version}")
        migrations = [migration for migration in migrations if migration.version <= target_version]

    with engine.connect() as connection:
        _require_core_schema(connection)
        _ensure_ledger(connection)
        acquired = connection.execute(
            text("SELECT GET_LOCK(:lock_name, 30)"), {"lock_name": MIGRATION_LOCK}
        ).scalar()
        connection.commit()
        if acquired != 1:
            raise RuntimeError("无法取得数据库迁移锁；可能有另一个迁移任务正在执行")

        try:
            applied = _latest_applied(connection)
            _validate_ledger_state(all_migrations, applied)
            pending = []
            for migration in migrations:
                row = applied.get(migration.version)
                if row is None:
                    pending.append(migration)
                elif row["checksum"] != migration.checksum:
                    if _checksum_repair_for(migration, row, migrations, applied):
                        continue
                    raise RuntimeError(
                        f"迁移 {migration.version} 已应用，但文件校验和变化；"
                        "请新增迁移修复，不要修改已发布迁移文件"
                    )

            if not pending:
                print("database_migrations=up_to_date")
                return 0

            if not no_backup:
                print(_run_backup())
            elif fresh_database_bootstrap:
                print("migration_backup=skipped fresh_database_bootstrap=true")

            applied_by = connection.execute(text("SELECT CURRENT_USER()")).scalar() or "unknown"
            for migration in pending:
                attempt_started = datetime.now()
                started = time.perf_counter()
                result = connection.execute(
                    text(
                        f"INSERT INTO {ATTEMPT_TABLE} "
                        "(version, checksum, status, started_at) "
                        "VALUES (:version, :checksum, 'RUNNING', :started_at)"
                    ),
                    {"version": migration.version, "checksum": migration.checksum, "started_at": attempt_started},
                )
                attempt_id = result.lastrowid
                connection.commit()
                try:
                    _apply_migration(connection, migration)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    connection.execute(
                        text(
                            f"INSERT INTO {LEDGER_TABLE} "
                            "(version, name, checksum, applied_at, duration_ms, applied_by) "
                            "VALUES (:version, :name, :checksum, :applied_at, :duration_ms, :applied_by)"
                        ),
                        {
                            "version": migration.version,
                            "name": migration.name,
                            "checksum": migration.checksum,
                            "applied_at": datetime.now(),
                            "duration_ms": duration_ms,
                            "applied_by": str(applied_by)[:128],
                        },
                    )
                    connection.commit()
                    connection.execute(
                        text(
                            f"UPDATE {ATTEMPT_TABLE} SET status='APPLIED', finished_at=:finished_at, "
                            "duration_ms=:duration_ms WHERE id=:attempt_id"
                        ),
                        {"finished_at": datetime.now(), "duration_ms": duration_ms, "attempt_id": attempt_id},
                    )
                    connection.commit()
                    print(f"migration_applied={migration.version}_{migration.name} duration_ms={duration_ms}")
                except Exception as exc:
                    connection.rollback()
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    connection.execute(
                        text(
                            f"UPDATE {ATTEMPT_TABLE} SET status='FAILED', finished_at=:finished_at, "
                            "duration_ms=:duration_ms, error_summary=:error_summary WHERE id=:attempt_id"
                        ),
                        {
                            "finished_at": datetime.now(),
                            "duration_ms": duration_ms,
                            "error_summary": str(exc)[:2000],
                            "attempt_id": attempt_id,
                        },
                    )
                    connection.commit()
                    raise RuntimeError(
                        f"迁移 {migration.version}_{migration.name} 失败；"
                        f"可检查执行记录后重试。原因：{exc}"
                    ) from exc
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": MIGRATION_LOCK})
            connection.commit()
    return 0


def migrate_to(version: str) -> int:
    """Compatibility entry point used by the historical one-file scripts."""

    return upgrade_database(target_version=version)


def main() -> int:
    parser = argparse.ArgumentParser(description="ChemicalOps MySQL 数据库迁移工具")
    parser.add_argument("command", choices=("status", "upgrade"), help="查看状态或按序应用待执行迁移")
    parser.add_argument("--target", help="升级到指定迁移版本（包含该版本）")
    parser.add_argument("--no-backup", action="store_true", help="仅开发/测试环境可使用；生产环境禁止")
    args = parser.parse_args()
    if args.command == "status":
        if args.target or args.no_backup:
            parser.error("status 命令不接受 --target 或 --no-backup")
        return status()
    return upgrade_database(target_version=args.target, no_backup=args.no_backup)


if __name__ == "__main__":
    raise SystemExit(main())
