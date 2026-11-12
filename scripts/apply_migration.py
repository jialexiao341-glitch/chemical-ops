"""执行 database/migrations 下的 SQL 迁移，不依赖 mysql 命令行客户端。

PowerShell 不支持 `mysql ... < file` 的输入重定向，统一用本脚本按已配置的连接执行；
`--dry-run` 只打印语句，不落库。迁移文件按 UTF-8 读取，忽略整行 `--` 注释。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def split_statements(sql: str) -> list[str]:
    """去掉整行注释与空行后按分号拆分；DDL 内没有字符串字面量分号。"""
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    statements = [part.strip() for part in "\n".join(lines).split(";")]
    return [statement for statement in statements if statement]


def apply(engine, statements: list[str], *, dry_run: bool = False) -> int:
    """依次执行语句；DDL 在 MySQL 隐式提交，失败即中断并返回已执行数量。"""
    if dry_run:
        for index, statement in enumerate(statements, start=1):
            head = statement.splitlines()[0][:80]
            print(f"[{index}] {head} ...")
        return 0
    applied = 0
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
            applied += 1
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path, help="迁移 SQL 路径，如 database/migrations/076_ai_eval_runs.sql")
    parser.add_argument("--dry-run", action="store_true", help="只打印语句，不执行")
    args = parser.parse_args(argv)
    try:
        statements = split_statements(args.file.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1
    if not statements:
        print("迁移文件没有可执行语句", file=sys.stderr)
        return 1
    if args.dry_run:
        apply(None, statements, dry_run=True)
        return 0
    url = get_settings().resolved_database_url
    try:
        engine = create_engine(url)
        applied = apply(engine, statements)
    except Exception as exc:  # noqa: BLE001 - 迁移失败需要原样报错
        print(f"迁移失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"已执行 {applied} 条语句：{args.file.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())