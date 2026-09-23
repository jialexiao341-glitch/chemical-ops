"""初始化全新 ChemicalOps 数据库并应用当前增量迁移。

本操作有意保持保守：schema.sql 是全新环境初始化脚本，包含 DROP TABLE。
当目标数据库中已经存在表时，本脚本会拒绝执行。
"""

from pathlib import Path
import re

import pymysql


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SCHEMA_FILE = ROOT / "database" / "schema.sql"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"Unsafe MySQL identifier: {value!r}")
    return f"`{value}`"


def account(user: str, host: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", user):
        raise ValueError(f"Unsafe MySQL user: {user!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.%-]+", host):
        raise ValueError(f"Unsafe MySQL host: {host!r}")
    return f"'{user}'@'{host}'"


def main() -> None:
    if not ENV_FILE.exists():
        raise SystemExit(f"Missing {ENV_FILE}. Copy .env.example to .env first.")
    if not SCHEMA_FILE.exists():
        raise SystemExit(f"Missing schema file: {SCHEMA_FILE}")

    cfg = load_env(ENV_FILE)
    required = (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DATABASE",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_ROOT_PASSWORD",
    )
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise SystemExit("Missing required .env values: " + ", ".join(missing))

    host = cfg["MYSQL_HOST"]
    port = int(cfg["MYSQL_PORT"])
    database = cfg["MYSQL_DATABASE"]
    username = cfg["MYSQL_USER"]
    charset = cfg.get("MYSQL_CHARSET", "utf8mb4")

    root_conn = pymysql.connect(
        host=host,
        port=port,
        user="root",
        password=cfg["MYSQL_ROOT_PASSWORD"],
        charset=charset,
        autocommit=True,
        connect_timeout=10,
    )
    try:
        with root_conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {quote_identifier(database)} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            for host_name in ("localhost", "127.0.0.1"):
                mysql_account = account(username, host_name)
                cursor.execute(
                    f"CREATE USER IF NOT EXISTS {mysql_account} IDENTIFIED BY %s",
                    (cfg["MYSQL_PASSWORD"],),
                )
                cursor.execute(
                    f"ALTER USER {mysql_account} IDENTIFIED BY %s",
                    (cfg["MYSQL_PASSWORD"],),
                )
                cursor.execute(
                    f"GRANT ALL PRIVILEGES ON {quote_identifier(database)}.* TO {mysql_account}"
                )
            cursor.execute("FLUSH PRIVILEGES")

            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=%s",
                (database,),
            )
            existing_count = int(cursor.fetchone()[0])
            if existing_count:
                raise SystemExit(
                    f"Refusing to run destructive initializer: {database!r} "
                    f"already contains {existing_count} table(s)."
                )
    finally:
        root_conn.close()

    app_conn = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=cfg["MYSQL_PASSWORD"],
        database=database,
        charset=charset,
        autocommit=True,
        connect_timeout=10,
    )
    try:
        statements = [
            statement.strip()
            for statement in SCHEMA_FILE.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]
        with app_conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
    finally:
        app_conn.close()

    # schema.sql 建立核心结构后，由统一 runner 补齐增量模块并写入迁移台账。
    # 该数据库刚经过空库检查，跳过备份；若中途失败，可运行 migrate_database.py upgrade 续跑。
    from migrate_database import upgrade_database

    upgrade_database(no_backup=True, fresh_database_bootstrap=True)
    print(f"database_ready={database}")
    print(f"created_table_count={len(tables)}")
    print("created_tables=" + ",".join(tables))


if __name__ == "__main__":
    main()
