"""Freeze 100 source-backed document RAG cases from the development knowledge base.

This script reads MySQL only. The checked-in JSONL is the reviewable evaluation input;
rerunning this builder after the corpus changes creates a new candidate set.
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


OUTPUT = ROOT / "docs" / "evaluation" / "rag_golden_100.jsonl"
PROPERTY_CAS = {
    "108-95-2", "110-54-3", "1310-58-3", "141-78-6", "64-17-5",
    "64-19-7", "67-56-1", "75-05-8", "75-09-2", "95-47-6",
}
FLASH_EXCLUDE = {"1310-58-3", "1310-73-2", "67-66-3", "75-09-2", "7664-41-7", "7647-01-0"}
BOILING_EXCLUDE = {"7664-41-7", "7647-01-0"}
UNKNOWN_CAS = [
    "71-43-2", "7732-18-5", "7647-14-5", "75-07-0", "67-63-0",
    "107-21-1", "50-00-0", "124-38-9", "74-82-8", "7782-44-7",
]
VAGUE_QUESTIONS = [
    "这种化学品的闪点是多少？", "该溶剂的沸点是多少？", "这份MSDS建议如何储存？",
    "这个物质的分子式是什么？", "此产品接触眼睛后如何急救？", "该物质可用什么灭火？",
    "这批材料的熔点是多少？", "请给出该化学品的密度。", "这个试剂的危险信号词是什么？",
    "这份TDS列出的分子量是多少？",
]


def extract(content: str, label: str, style: str) -> str | None:
    if style == "line":
        pattern = rf"{re.escape(label)}\s*\n+\s*([^\n]{{1,70}})"
    elif style == "tds":
        pattern = rf"{re.escape(label)}:\s*\n+\s*([^\n]{{1,70}})"
    else:
        pattern = rf"{re.escape(label)}\s*([^\n]{{1,90}})"
    match = re.search(pattern, content, re.IGNORECASE)
    return match.group(1).strip() if match else None


def case(question: str, row: dict, value: str, field: str) -> dict:
    value = " ".join(value.split())
    return {
        "kind": "answerable",
        "question": question,
        "cas_no": row["cas_no"],
        "chemical_name": row["name_zh"],
        "field": field,
        "expected_value": value,
        "gold_section_ids": [row["id"]],
        "gold_document_id": row["document_id"],
        "gold_doc_type": row["doc_type"],
        "gold_section_key": row["section_key"],
        "evidence_sha256": hashlib.sha256(row["content"].encode("utf-8")).hexdigest(),
        "evidence_excerpt": value,
    }


def main() -> None:
    engine = create_engine(get_settings().resolved_database_url)
    try:
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(text("""
                SELECT s.id, s.document_id, s.cas_no, s.doc_type, s.section_no,
                       s.section_key, s.title, s.content, d.name_zh
                FROM ai_document_sections s JOIN ai_documents d ON d.id=s.document_id
                WHERE d.parse_status='PARSED' ORDER BY s.cas_no, s.doc_type, s.id
            """)).mappings()]
    finally:
        engine.dispose()

    cases: list[dict] = []
    for row in rows:
        cas, name, doc_type = row["cas_no"], row["name_zh"], row["doc_type"]
        if doc_type == "tds" and row["section_no"] == 1:
            value = extract(row["content"], "Molecular Formula", "tds")
            if value:
                cases.append(case(f"根据 {name}（CAS {cas}）的 TDS，它的分子式是什么？", row, value, "molecular_formula"))
        if doc_type == "property" and cas in PROPERTY_CAS and (row["title"] or "").endswith(" Properties"):
            for field, label, zh in (
                ("melting_point", "Melting point", "熔点"),
                ("boiling_point", "Boiling point", "沸点"),
            ):
                value = extract(row["content"], label, "line")
                if value:
                    cases.append(case(f"物性资料中，{name}（CAS {cas}）的{zh}是多少？", row, value, field))
        if doc_type == "msds" and row["section_no"] == 9:
            if cas not in FLASH_EXCLUDE:
                value = extract(row["content"], "Flash point", "inline")
                if value and "°C" in value:
                    value = value.split("°C", 1)[0].strip() + " °C"
                    cases.append(case(f"{name}（CAS {cas}）的 MSDS 第9节记录的闪点是多少？", row, value, "flash_point"))
            if cas not in BOILING_EXCLUDE:
                value = extract(row["content"], "Initial boiling point and boiling range", "inline")
                if value and "°C" in value:
                    value = value.split("°C", 1)[0].strip() + " °C"
                    cases.append(case(f"按 {name}（CAS {cas}）的 MSDS 第9节，初沸点或沸程是多少？", row, value, "boiling_point"))
    assert len(cases) == 69, f"answerable candidate count changed: {len(cases)}"
    ethanol = next(r for r in rows if r["cas_no"] == "64-17-5" and r["doc_type"] == "msds" and r["section_no"] == 9)
    value = extract(ethanol["content"], "Melting point/range:", "inline")
    assert value and "°C" in value
    cases.append(case("乙醇（CAS 64-17-5）的 MSDS 第9节给出的熔点是多少？", ethanol, value.split("°C", 1)[0].strip() + " °C", "melting_point"))

    known_tds = [c for c in cases if c["field"] == "molecular_formula"][:10]
    for cas in UNKNOWN_CAS:
        cases.append({"kind": "no_evidence", "question": f"知识库中 CAS {cas} 的 MSDS 闪点是多少？", "cas_no": cas,
                      "gold_section_ids": [], "expected_behavior": "abstain", "reason": "CAS absent from parsed corpus"})
    for item in known_tds:
        name, cas = item["chemical_name"], item["cas_no"]
        cases.append({"kind": "no_evidence", "question": f"{name}（CAS {cas}）的 TDS 中，2027 年批次 CO-2027 的实测纯度是多少？",
                      "cas_no": cas, "gold_section_ids": [], "expected_behavior": "abstain", "reason": "future batch result absent from source"})
    for question in VAGUE_QUESTIONS:
        cases.append({"kind": "needs_target", "question": question, "cas_no": None,
                      "gold_section_ids": [], "expected_behavior": "clarify", "reason": "chemical target unspecified"})
    assert len(cases) == 100
    for index, item in enumerate(cases, 1):
        item["id"] = f"RAG-{index:03d}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUTPUT}")
    print("Kinds:", {kind: sum(c["kind"] == kind for c in cases) for kind in ("answerable", "no_evidence", "needs_target")})


if __name__ == "__main__":
    main()
