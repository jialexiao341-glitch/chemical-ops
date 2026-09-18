"""下载、清洗并幂等导入一批常用化学品基础数据。

数据来源：PubChem PUG REST。
导入目标：md_chemicals。

默认行为是：
1. 按 CAS 号从 PubChem 查询分子式、分子量和 IUPAC 名称；
2. 清洗字段并生成带来源说明的标准记录；
3. 已存在相同 CAS 号时跳过，不覆盖已有业务数据；
4. 将原始响应、清洗结果和导入统计保存到 storage/imports/pubchem/。

示例：
    python scripts/import_pubchem_chemicals.py
    python scripts/import_pubchem_chemicals.py --dry-run
    python scripts/import_pubchem_chemicals.py --limit 5
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.modules.chemicals.model import Chemical  # noqa: E402


PUBCHEM_PROPERTY_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
    "{identifier}/property/IUPACName,MolecularFormula,MolecularWeight/JSON"
)
IMPORT_ROOT = ROOT / "storage" / "imports" / "pubchem"


# 中文名称和英文常用名来自项目的导入清单，化学属性由 PubChem 返回。
DEFAULT_CHEMICALS = (
    ("乙醇", "Ethanol", "64-17-5"),
    ("甲醇", "Methanol", "67-56-1"),
    ("丙酮", "Acetone", "67-64-1"),
    ("乙酸", "Acetic acid", "64-19-7"),
    ("盐酸", "Hydrochloric acid", "7647-01-0"),
    ("硫酸", "Sulfuric acid", "7664-93-9"),
    ("硝酸", "Nitric acid", "7697-37-2"),
    ("氢氧化钠", "Sodium hydroxide", "1310-73-2"),
    ("氢氧化钾", "Potassium hydroxide", "1310-58-3"),
    ("氨", "Ammonia", "7664-41-7"),
    ("过氧化氢", "Hydrogen peroxide", "7722-84-1"),
    ("次氯酸钠", "Sodium hypochlorite", "7681-52-9"),
    ("甲苯", "Toluene", "108-88-3"),
    ("邻二甲苯", "o-Xylene", "95-47-6"),
    ("正己烷", "n-Hexane", "110-54-3"),
    ("乙酸乙酯", "Ethyl acetate", "141-78-6"),
    ("乙腈", "Acetonitrile", "75-05-8"),
    ("二氯甲烷", "Dichloromethane", "75-09-2"),
    ("氯仿", "Chloroform", "67-66-3"),
    ("苯酚", "Phenol", "108-95-2"),
)


def clean_text(value: Any) -> str | None:
    """去除空白和不可见字符，空值统一为 None。"""

    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def valid_cas(cas_no: str) -> bool:
    """校验 CAS 格式和末位校验码，避免脏数据进入唯一字段。"""

    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", cas_no):
        return False
    digits = cas_no.replace("-", "")
    check_digit = int(digits[-1])
    weighted_sum = sum(int(digit) * index for index, digit in enumerate(reversed(digits[:-1]), start=1))
    return weighted_sum % 10 == check_digit


def clean_decimal(value: Any) -> Decimal | None:
    """将 PubChem 分子量转换为数据库 Numeric(18, 6) 可接受的数值。"""

    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        return None


def fetch_properties(identifier: str, delay_seconds: float) -> dict[str, Any]:
    """从 PubChem 查询一个化学品的标准属性。"""

    url = PUBCHEM_PROPERTY_URL.format(identifier=quote(identifier, safe=""))
    try:
        # Windows 环境下优先复用系统 curl，通常比 Python 直连更容易正确使用系统代理。
        result = subprocess.run(
            ["curl.exe", "--fail", "--silent", "--show-error", "--max-time", "10", "--user-agent", "ChemicalOps-data-import/1.0", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        payload = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError("系统未找到 curl.exe，无法访问 PubChem") from exc
    except subprocess.CalledProcessError as exc:
        reason = clean_text(exc.stderr) or "未知网络错误"
        raise RuntimeError(f"PubChem 请求失败：{reason}，查询值 {identifier}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"PubChem 返回内容不是有效 JSON，查询值 {identifier}") from exc
    finally:
        # 按官方服务建议控制请求频率，避免连续请求触发限流。
        time.sleep(delay_seconds)

    properties = payload.get("PropertyTable", {}).get("Properties", [])
    if not properties:
        raise RuntimeError(f"PubChem 未返回化学品属性：{identifier}")
    return properties[0]


def build_row(chemical_name: str, english_name: str, cas_no: str, properties: dict[str, Any]) -> dict[str, Any]:
    """把外部响应转换为 md_chemicals 对应字段。"""

    if not valid_cas(cas_no):
        raise ValueError(f"CAS 号格式或校验码不正确：{cas_no}")
    cid = properties.get("CID")
    return {
        "chemical_name": clean_text(chemical_name),
        "english_name": clean_text(english_name),
        "alias_text": clean_text(properties.get("IUPACName")),
        "cas_no": cas_no,
        "chemical_formula": clean_text(properties.get("MolecularFormula")),
        "molecular_weight": clean_decimal(properties.get("MolecularWeight")),
        "hazard_class": None,
        "source_text": f"PubChem PUG REST；CID={cid}；CAS={cas_no}",
        "status": "ACTIVE",
        "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}" if cid else None,
    }


def write_outputs(run_dir: Path, raw_payloads: dict[str, Any], rows: list[dict[str, Any]], stats: dict[str, int]) -> None:
    """保存可追溯的原始下载结果、清洗结果和统计信息。"""

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw_pubchem.json").write_text(json.dumps(raw_payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    serializable_rows = [{key: (str(value) if isinstance(value, Decimal) else value) for key, value in row.items()} for row in rows]
    (run_dir / "cleaned_chemicals.json").write_text(json.dumps(serializable_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        with (run_dir / "cleaned_chemicals.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(serializable_rows[0]))
            writer.writeheader()
            writer.writerows(serializable_rows)


def import_rows(rows: list[dict[str, Any]], dry_run: bool) -> tuple[int, int]:
    """幂等导入数据库，返回新增数量和已存在数量。"""

    if dry_run:
        return len(rows), 0

    db = SessionLocal()
    created_count = 0
    skipped_count = 0
    try:
        for row in rows:
            existing = db.scalar(select(Chemical).where(Chemical.cas_no == row["cas_no"]))
            if existing is not None:
                skipped_count += 1
                continue
            db.add(Chemical(**{key: value for key, value in row.items() if key != "source_url"}))
            created_count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return created_count, skipped_count


def parse_args() -> argparse.Namespace:
    """解析导入参数。"""

    parser = argparse.ArgumentParser(description="下载并导入 PubChem 常用化学品基础数据")
    parser.add_argument("--limit", type=int, default=len(DEFAULT_CHEMICALS), help="最多处理多少条默认化学品，默认 20 条")
    parser.add_argument("--delay", type=float, default=0.25, help="请求间隔秒数，默认 0.25 秒")
    parser.add_argument("--dry-run", action="store_true", help="只下载和清洗，不写入数据库")
    return parser.parse_args()


def main() -> None:
    """执行下载、清洗、落盘和入库流程。"""

    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit 必须大于 0")
    if args.delay < 0.2:
        raise SystemExit("为遵守 PubChem 服务频率建议，--delay 不能小于 0.2 秒")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = IMPORT_ROOT / run_id
    selected = DEFAULT_CHEMICALS[: args.limit]
    raw_payloads: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for chemical_name, english_name, cas_no in selected:
        try:
            lookup_identifier = cas_no
            try:
                properties = fetch_properties(cas_no, args.delay)
            except RuntimeError as cas_error:
                # 部分混合物没有可直接匹配的单一 CAS，回退到英文常用名查询。
                try:
                    lookup_identifier = english_name
                    properties = fetch_properties(english_name, args.delay)
                except RuntimeError:
                    raise cas_error
            raw_payloads[cas_no] = properties
            rows.append(build_row(chemical_name, english_name, cas_no, properties))
            print(f"downloaded cas={cas_no} name={chemical_name} lookup={lookup_identifier}")
        except (RuntimeError, ValueError) as exc:
            failures.append(str(exc))
            print(f"failed cas={cas_no} reason={exc}")

    stats = {
        "requested": len(selected),
        "downloaded": len(rows),
        "failed": len(failures),
        "created": 0,
        "skipped_existing": 0,
    }
    write_outputs(run_dir, raw_payloads, rows, stats)
    created_count, skipped_count = import_rows(rows, args.dry_run)
    stats["created"] = created_count
    stats["skipped_existing"] = skipped_count
    (run_dir / "stats.json").write_text(json.dumps({**stats, "failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"run_dir={run_dir}")
    print(f"requested={stats['requested']}")
    print(f"downloaded={stats['downloaded']}")
    print(f"failed={stats['failed']}")
    print(f"created={stats['created']}")
    print(f"skipped_existing={stats['skipped_existing']}")
    print(f"dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
