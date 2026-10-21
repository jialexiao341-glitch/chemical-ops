"""将逻辑备份恢复到指定 MySQL 数据库；必须显式确认。"""

from __future__ import annotations

import argparse
import mmap
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="ChemicalOps MySQL 恢复")
    parser.add_argument("backup", type=Path, help="待恢复的 .sql 文件")
    parser.add_argument("--confirm", action="store_true", help="确认目标数据库将被备份内容覆盖")
    parser.add_argument("--database", required=True, help="显式指定预先创建的恢复目标库")
    parser.add_argument("--allow-configured-target", action="store_true", help="允许恢复到当前配置库；隔离演练禁止使用")
    args = parser.parse_args()
    if not args.confirm:
        print("恢复是破坏性操作，请加入 --confirm；生产环境先完成备份和变更审批。", file=sys.stderr)
        return 2
    if args.backup.suffix.lower() != ".sql" or not args.backup.is_file():
        print("备份文件不存在或不是 .sql 文件", file=sys.stderr)
        return 2
    settings = get_settings()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", args.database):
        parser.error("目标数据库名称只允许字母、数字和下划线")
    if args.database == settings.mysql_database and not args.allow_configured_target:
        parser.error("隔离恢复不能使用当前配置库；正式恢复须显式 --allow-configured-target")
    # Logical backups produced by backup_mysql omit CREATE DATABASE/USE. Scan
    # across line breaks (including executable comments) without loading a large
    # dump into Python memory before opening a client.
    sql_separator = rb"(?:\s|/\*.*?\*/|--[^\r\n]*|\#[^\r\n]*)+"
    redirect_pattern = re.compile(
        rb"\b(?:USE" + sql_separator + rb"|(?:CREATE|DROP|ALTER)" + sql_separator + rb"DATABASE\b)",
        re.I | re.S,
    )
    with args.backup.open("rb") as source:
        if args.backup.stat().st_size:
            with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as dump:
                if redirect_pattern.search(dump):
                    parser.error("备份包含数据库切换或数据库级 DDL；请使用单库备份")
    mysql = os.environ.get("MYSQL_CLIENT_PATH") or shutil.which("mysql")
    if not mysql:
        print("mysql 客户端未安装或不在 PATH 中", file=sys.stderr)
        return 2
    command = [mysql, "--binary-mode", "--host", settings.mysql_host, "--port", str(settings.mysql_port), "--user", settings.mysql_user, args.database]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = settings.mysql_password
    with args.backup.open("rb") as handle:
        completed = subprocess.run(command, stdin=handle, stderr=subprocess.PIPE, env=environment, check=False)
    if completed.returncode != 0:
        print(completed.stderr.decode("utf-8", errors="replace")[-2000:], file=sys.stderr)
        return completed.returncode or 1
    print(f"mysql_restore=ok database={args.database} backup={args.backup.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
