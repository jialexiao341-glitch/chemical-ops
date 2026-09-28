"""将逻辑备份恢复到指定 MySQL 数据库；必须显式确认。"""

from __future__ import annotations

import argparse
import os
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
    args = parser.parse_args()
    if not args.confirm:
        print("恢复是破坏性操作，请加入 --confirm；生产环境先完成备份和变更审批。", file=sys.stderr)
        return 2
    if args.backup.suffix.lower() != ".sql" or not args.backup.is_file():
        print("备份文件不存在或不是 .sql 文件", file=sys.stderr)
        return 2
    mysql = shutil.which("mysql")
    if not mysql:
        print("mysql 客户端未安装或不在 PATH 中", file=sys.stderr)
        return 2
    settings = get_settings()
    command = [mysql, "--host", settings.mysql_host, "--port", str(settings.mysql_port), "--user", settings.mysql_user, settings.mysql_database]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = settings.mysql_password
    with args.backup.open("rb") as handle:
        completed = subprocess.run(command, stdin=handle, stderr=subprocess.PIPE, env=environment, check=False)
    if completed.returncode != 0:
        print(completed.stderr.decode("utf-8", errors="replace")[-2000:], file=sys.stderr)
        return completed.returncode or 1
    print(f"mysql_restore=ok database={settings.mysql_database} backup={args.backup.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
