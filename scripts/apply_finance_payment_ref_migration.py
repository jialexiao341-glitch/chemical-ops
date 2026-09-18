"""为付款银行流水号增加数据库唯一约束。"""

from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def main() -> None:
    """执行付款银行流水号唯一索引迁移。"""
    path = Path(__file__).resolve().parents[1] / "database" / "migrations" / "014_finance_payment_transaction_ref.sql"
    engine = create_engine(get_settings().resolved_database_url)
    with engine.begin() as connection:
        index_names = {row[2] for row in connection.execute(text("SHOW INDEX FROM finance_payments"))}
        if "uk_finance_payment_transaction_ref" not in index_names:
            connection.exec_driver_sql(path.read_text(encoding="utf-8"))
    print("finance_payment_ref_migration_ready=true")


if __name__ == "__main__":
    main()
