"""生成 MySQL 逻辑备份；密码只通过 MYSQL_PWD 传给 mysqldump。"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys

from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="ChemicalOps MySQL 备份")
    parser.add_argument("--output-dir", default="backups/mysql", help="备份目录")
    parser.add_argument("--keep", type=int, default=14, help="保留最近多少个 .sql 文件")
    args = parser.parse_args()
    if args.keep < 1:
        parser.error("--keep 必须大于 0")
    configured_dump = os.environ.get("MYSQLDUMP_PATH", "").strip()
    dump = str(Path(configured_dump).expanduser()) if configured_dump else shutil.which("mysqldump")
    if dump and not Path(dump).is_file():
        print("MYSQLDUMP_PATH 指定的文件不存在", file=sys.stderr)
        return 2
    if not dump:
        print("mysqldump 未安装或不在 PATH 中；可通过 MYSQLDUMP_PATH 指定 mysqldump.exe", file=sys.stderr)
        return 2
    settings = get_settings()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = output_dir / f"chemicalops_{timestamp}.sql"
    command = [
        dump,
        "--single-transaction",
        "--routines",
        "--events",
        "--triggers",
        "--hex-blob",
        "--host", settings.mysql_host,
        "--port", str(settings.mysql_port),
        "--user", settings.mysql_user,
        settings.mysql_database,
    ]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = settings.mysql_password
    with output.open("wb") as handle:
        completed = subprocess.run(command, stdout=handle, stderr=subprocess.PIPE, env=environment, check=False)
    if completed.returncode != 0:
        output.unlink(missing_ok=True)
        print(completed.stderr.decode("utf-8", errors="replace")[-2000:], file=sys.stderr)
        return completed.returncode or 1
    backups = sorted(output_dir.glob("chemicalops_*.sql"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in backups[args.keep:]:
        stale.unlink()
    print(f"mysql_backup={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
