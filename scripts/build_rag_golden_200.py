"""Create a frozen 200-case document RAG suite from parsed MySQL sections.

The answer key is the cited document text, not an independently validated
chemical property. The script reads MySQL and writes one JSONL artifact.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.modules.chemicals.cas import valid_cas_checksum  # noqa: E402


OUTPUT = ROOT / "docs" / "evaluation" / "rag_golden_200.jsonl"
PROPERTY_EXCLUDE = {"1310-73-2", "7664-41-7"}
FLASH_EXCLUDE = {"75-21-8", "7647-01-0", "7647-14-5", "7664-41-7", "7664-93-9", "7697-37-2"}
BOILING_EXCLUDE = {"7664-41-7"}
TDS_EXCLUDE = {"108-24-7"}
UNKNOWN_CAS = [
    "7732-18-5", "75-07-0", "124-38-9", "74-82-8", "7782-44-7",
    "74-84-0", "75-18-3", "74-98-6", "74-85-1", "75-15-0",
    "106-99-0", "56-23-5", "107-13-1", "107-06-2", "630-08-0",
]
MISSING_SOURCE_QUESTIONS = [
    ("60-29-7", "CAS 60-29-7 的 MSDS 第9节记载的闪点是多少？"),
    ("60-29-7", "CAS 60-29-7 的物性页记载的熔点是多少？"),
    ("75-21-8", "CAS 75-21-8 的 TDS 记载的分子式是什么？"),
    ("7783-06-4", "CAS 7783-06-4 的 TDS 记载的分子量是多少？"),
    ("78-93-3", "CAS 78-93-3 的物性页记载的熔点是多少？"),
]
VAGUE_QUESTIONS = [
    "这种化学品的 MSDS 第9节闪点是多少？", "该试剂的沸点是多少？",
    "这份 TDS 记录的分子式是什么？", "这个物质的熔点是多少？",
    "该溶剂的物性页密度是多少？", "这份 MSDS 的急救措施是什么？",
    "此化学品的消防灭火建议是什么？", "该材料的储存条件是什么？",
    "这个产品的蒸气压是多少？", "这份安全数据表的危险信号词是什么？",
    "它的分子量是多少？", "这瓶试剂的自燃温度是多少？",
    "请给出该物质的溶解度。", "这个溶剂的 MSDS 第2节写了什么？",
    "这份物性资料的沸点范围是多少？", "该化学品的爆炸极限是多少？",
    "它接触眼睛后该如何急救？", "这份 TDS 里的纯度规格是多少？",
    "这种物质的外观是什么？", "该试剂的 MSDS 第14节运输信息是什么？",
]


def line_value(content: str, label: str, *, tds: bool = False) -> str | None:
    colon = ":" if tds else ""
    match = re.search(rf"{re.escape(label)}{colon}\s*\n+\s*([^\n]{{1,80}})", content, re.IGNORECASE)
    return " ".join(match.group(1).split()) if match else None


def temperature(content: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}\s*([^\n]{{1,120}})", content, re.IGNORECASE)
    if not match or "°C" not in match.group(1):
        return None
    value = " ".join((match.group(1).split("°C", 1)[0] + " °C").split())
    return value if re.search(r"\d", value) and "no data" not in value.lower() and "does not" not in value.lower() else None


def record(row: dict, name: str, field: str, value: str, question: str) -> dict:
    return {
        "kind": "answerable", "question": question, "cas_no": row["cas_no"],
        "chemical_name": name, "field": field, "expected_value": value,
        "gold_section_ids": [row["id"]], "gold_document_id": row["document_id"],
        "gold_doc_type": row["doc_type"], "gold_section_key": row["section_key"],
        "evidence_sha256": hashlib.sha256(row["content"].encode("utf-8")).hexdigest(),
        "evidence_excerpt": value,
    }


def main() -> None:
    engine = create_engine(get_settings().resolved_database_url)
    try:
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text("""
                SELECT s.id, s.document_id, s.cas_no, s.doc_type, s.section_no,
                       s.section_key, s.title, s.content, d.name_zh,
                       d.title AS document_title
                FROM ai_document_sections s JOIN ai_documents d ON d.id=s.document_id
                WHERE d.parse_status='PARSED' ORDER BY s.cas_no, s.doc_type, s.id
            """)).mappings()]
    finally:
        engine.dispose()

    name_by_cas: dict[str, str] = {}
    for row in rows:
        if row["name_zh"]:
            name_by_cas[row["cas_no"]] = row["name_zh"]
        elif row["doc_type"] == "msds" and row["document_title"] and row["cas_no"] not in name_by_cas:
            name_by_cas[row["cas_no"]] = row["document_title"].strip()
        elif row["doc_type"] == "tds" and row["cas_no"] not in name_by_cas:
            product = line_value(row["content"], "Product Name", tds=True)
            if product:
                name_by_cas[row["cas_no"]] = product

    msds: list[dict] = []
    property_cases: list[dict] = []
    tds: list[dict] = []
    known_cas = {row["cas_no"] for row in rows}
    for row in rows:
        cas = row["cas_no"]
        name = name_by_cas.get(cas, cas)
        if row["doc_type"] == "msds" and row["section_no"] == 9:
            if cas not in FLASH_EXCLUDE:
                value = temperature(row["content"], "Flash point")
                if value:
                    msds.append(record(row, name, "flash_point", value, f"按 {name}（CAS {cas}）的 MSDS 第9节，闪点是多少？"))
            if cas not in BOILING_EXCLUDE:
                value = temperature(row["content"], "Initial boiling point and boiling range")
                if value:
                    msds.append(record(row, name, "boiling_point", value, f"{name}（CAS {cas}）的 MSDS 第9节给出的初沸点或沸程是多少？"))
            if cas in {"64-17-5", "71-43-2"}:
                value = temperature(row["content"], "Melting point/range:")
                if value:
                    msds.append(record(row, name, "melting_point", value, f"请按 {name}（CAS {cas}）MSDS 第9节回答熔点。"))
        if row["doc_type"] == "property" and cas not in PROPERTY_EXCLUDE and (row["title"] or "").endswith(" Properties"):
            for field, label, zh in (
                ("melting_point", "Melting point", "熔点"),
                ("boiling_point", "Boiling point", "沸点"),
            ):
                value = line_value(row["content"], label)
                if value and re.search(r"\d", value):
                    property_cases.append(record(row, name, field, value, f"在 {name}（CAS {cas}）的物性页中，{zh}记录为多少？"))
        if row["doc_type"] == "tds" and row["section_no"] == 1 and cas not in TDS_EXCLUDE:
            formula = line_value(row["content"], "Molecular Formula", tds=True)
            weight = line_value(row["content"], "Molecular Weight", tds=True)
            if formula and weight:
                tds.append(record(row, name, "molecular_formula", formula, f"{name}（CAS {cas}）的 TDS 标注了什么分子式？"))
                tds.append(record(row, name, "molecular_weight", weight, f"根据 {name}（CAS {cas}）的 TDS，分子量是多少？"))

    assert (len(msds), len(property_cases), len(tds)) == (50, 40, 50), (len(msds), len(property_cases), len(tds))
    assert all(valid_cas_checksum(cas) and cas not in known_cas for cas in UNKNOWN_CAS)
    cases = msds + property_cases + tds
    for cas in UNKNOWN_CAS:
        cases.append({"kind": "no_evidence", "question": f"知识库中 CAS {cas} 的 MSDS 第9节闪点是多少？",
                      "cas_no": cas, "gold_section_ids": [], "expected_behavior": "abstain", "reason": "CAS absent from parsed corpus"})
    for cas, question in MISSING_SOURCE_QUESTIONS:
        cases.append({"kind": "no_evidence", "question": question, "cas_no": cas,
                      "gold_section_ids": [], "expected_behavior": "abstain", "reason": "requested document type absent"})
    for item in tds[:40:2]:
        cas, name = item["cas_no"], item["chemical_name"]
        cases.append({"kind": "no_evidence", "question": f"{name}（CAS {cas}）的 TDS 中，2027 年批次 CO-2027 的实测纯度是多少？",
                      "cas_no": cas, "gold_section_ids": [], "expected_behavior": "abstain", "reason": "future batch result absent from source"})
    for question in VAGUE_QUESTIONS:
        cases.append({"kind": "needs_target", "question": question, "cas_no": None,
                      "gold_section_ids": [], "expected_behavior": "clarify", "reason": "chemical target unspecified"})
    assert len(cases) == 200 and len({c["question"] for c in cases}) == 200
    for index, item in enumerate(cases, 1):
        item["id"] = f"RAG200-{index:03d}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUTPUT}")
    print("Answerable by source:", {k: len(v) for k, v in (("msds", msds), ("property", property_cases), ("tds", tds))})
    print("Kinds:", {kind: sum(c["kind"] == kind for c in cases) for kind in ("answerable", "no_evidence", "needs_target")})


if __name__ == "__main__":
    main()
