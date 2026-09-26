"""Create a restorable, local JSONL snapshot of the development database.

Rows are stored with their SQL column names and type-tagged binary values. The
snapshot includes account data, so keep it private and do not commit it.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db import engine  # noqa: E402


def encode(value: object) -> object:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    return value


def main() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("Refusing to snapshot a non-development database")
    from datetime import timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = ROOT / "backups" / "mysql"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"pre-curated-rebuild-{stamp}.jsonl.gz"
    tables = inspect(engine).get_table_names()
    counts: dict[str, int] = {}
    with engine.connect() as connection, gzip.open(destination, "wt", encoding="utf-8") as output:
        output.write(json.dumps({"format": 1, "database": settings.mysql_database, "created_at": stamp, "tables": tables}) + "\n")
        for table in tables:
            rows = connection.execute(text(f"SELECT * FROM `{table}`")).mappings()
            count = 0
            for row in rows:
                output.write(json.dumps({"table": table, "row": {key: encode(value) for key, value in row.items()}}, ensure_ascii=False) + "\n")
                count += 1
            counts[table] = count
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(json.dumps({"backup": str(destination), "sha256": digest, "tables": len(tables), "rows": sum(counts.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
