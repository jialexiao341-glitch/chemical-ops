"""Add a small set of linked procurement cases to the local development database.

The records are constructed business samples, not evidence of actual transactions.
Keep their provenance in environment documentation, separate from business fields.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from extend_curated_dataset import PurchaseRequest, SessionLocal, get_settings, main_seed, verify


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    (327, "PRD-ACETONITRILE-AR", 36, 118, "分析实验室因色谱方法确认批次增加，申请补充乙腈；到货时核对批号与纯度证明", "RECEIVED", 0),
    (328, "PRD-H2O2-AR", 48, 34, "环境监测组为季度采样计划补充过氧化氢，需核查包装完整性及有效期", "DOCUMENT", 1),
    (329, "PRD-ETHANOL-AR", 96, 74, "质量控制室留样复测量增加，申请无水乙醇并核对分批到货数量", "SHORT", 2),
    (330, "PRD-NAOH-AR", 120, 16, "水处理班组调整中和工序储备，需在月末前补足氢氧化钠", "TRANSIT", 1),
    (331, "PRD-TOLUENE-AR", 40, 81, "材料研发组启动相容性试验，按现行规格采购甲苯并核对供货周期", "ORDERED", 0),
    (332, "PRD-ETHYLACETATE-AR", 60, 71, "工艺开发组开展分离纯化验证，比较乙酸乙酯报价与交期", "RFQ", 1),
    (333, "PRD-HCL-AR", 72, 22, "设备保障组检修后需要补充盐酸，申请确认仓区接收条件和交期", "SUBMITTED", 2),
    (334, "PRD-ACETIC-AR", 30, 31, "研发小试新增缓冲液配制任务，拟采购冰醋酸并核对技术规格", "DRAFT", 0),
    (335, "PRD-METHANOL-AR", 52, 61, "仪器平台增加方法验证批次，申请甲醇并核对随货批次资料", "RECEIVED", 1),
    (336, "PRD-SULFURIC-AR", 84, 28, "园区公用工程计划维护循环水系统，硫酸到货后须核对数量和随货证明", "DOCUMENT", 2),
)


def check_backup(path: Path, database: str) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "backups" / "mysql").resolve()):
        raise SystemExit("Backup must be under backups/mysql")
    if not resolved.is_file() or resolved.stat().st_size < 1024:
        raise SystemExit("A nonempty development database backup is required")
    with gzip.open(resolved, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
    if header.get("database") != database:
        raise SystemExit("Backup database does not match the target")
    stamp = datetime.strptime(header["created_at"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if abs((datetime.now(timezone.utc) - stamp).total_seconds()) > 3600:
        raise SystemExit("Backup must have been created within the last hour")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-transaction", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.app_env != "development" or settings.mysql_host not in {"localhost", "127.0.0.1"} or settings.mysql_database != "chemicalops":
        raise SystemExit("Only the local ChemicalOps development database may be changed")
    if args.apply or args.validate_transaction:
        if args.backup is None:
            raise SystemExit("A recent --backup is required")
        check_backup(args.backup, settings.mysql_database)

    numbers = [number for number, *_ in CASES]
    expected = {f"PR-2026-{number:04d}" for number in numbers}
    with SessionLocal() as db:
        found = set(db.scalars(select(PurchaseRequest.request_no).where(PurchaseRequest.request_no.in_(expected))).all())
        if found == expected:
            print(json.dumps({"already_applied": True, "case_count": len(CASES)}))
            return
        if found:
            raise SystemExit(f"Partial import detected: {sorted(found)}")
        if not (args.apply or args.validate_transaction):
            print(json.dumps({"dry_run": True, "case_count": len(CASES), "request_numbers": sorted(expected)}))
            return
        try:
            counts = main_seed(db, cases=CASES, add_master=False)
            verify(db)
            if args.validate_transaction:
                db.rollback()
            else:
                db.commit()
        except Exception:
            db.rollback()
            raise
    print(json.dumps({"rolled_back": args.validate_transaction, "created": counts}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
