"""逐表提取 Word 中的 MSDS 原文，不改写事实。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


def valid_cas(value: str) -> bool:
    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", value):
        return False
    digits = value.replace("-", "")
    return sum(int(digit) * weight for weight, digit in enumerate(reversed(digits[:-1]), 1)) % 10 == int(digits[-1])


def extract(path: Path) -> dict:
    document = Document(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    heading = ""
    records = []
    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document)
            if paragraph.style.name.startswith("Heading") and paragraph.text.strip():
                heading = paragraph.text.strip()
        elif element.tag == qn("w:tbl"):
            table = Table(element, document)
            rows = []
            for number, row in enumerate(table.rows, 1):
                cells = []
                previous = None
                for cell in row.cells:
                    if cell._tc is previous:
                        continue
                    previous = cell._tc
                    cells.append(cell.text.strip())
                rows.append({"row": number, "cells": cells})
            first_rows = " ".join(text for row in rows[:4] for text in row["cells"])
            match = re.search(r"CAS\s*号\s*[：:]\s*([\d－—–-]+)", first_rows, re.I)
            cas_raw = match.group(1) if match else None
            cas = unicodedata.normalize("NFKC", cas_raw).replace("−", "-").replace("—", "-").replace("–", "-") if cas_raw else None
            title = re.sub(r"^表\s*1\s*[-.][\d.]+\s*", "", unicodedata.normalize("NFKC", heading)).strip()
            records.append({
                "document_type": "msds", "status": "DRAFT", "published": False,
                "source_table": len(records) + 1, "source_heading": heading,
                "name_from_heading": title, "cas_raw": cas_raw,
                "cas_candidate": cas, "cas_valid_checksum": valid_cas(cas) if cas else None,
                "rows": rows,
            })
    return {"source": {"filename": path.name, "sha256": digest, "format": "docx"},
            "status": "DRAFT", "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split-dir", type=Path, help="Write one review file per source table")
    args = parser.parse_args()
    result = extract(args.source)
    if args.split_dir:
        args.split_dir.mkdir(parents=True, exist_ok=True)
        index = []
        for record in result["records"]:
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', record['name_from_heading']).strip(' .')[:60] or '未命名'
            filename = f"{record['source_table']:03d}-{safe_name}.json"
            (args.split_dir / filename).write_text(
                json.dumps({"source": result["source"], **record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            index.append({key: record[key] for key in ("source_table", "source_heading", "name_from_heading", "cas_raw", "cas_candidate", "cas_valid_checksum", "status")})
            index[-1]["file"] = filename
        result["records"] = index
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(result['records'])} draft tables to {args.output}")


if __name__ == "__main__":
    main()
