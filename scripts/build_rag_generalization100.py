"""Freeze new RAG questions directly from parsed SQL evidence, without retrieval or LLM.

This source-backed extension tests new fields and question structures. It is not
an independently annotated benchmark or a holdout of entirely new documents.
"""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from app.modules.ai.intent import valid_cas_checksum  # noqa: E402

OUTPUT = ROOT / "docs/evaluation/rag-generalization-100-20261009_cases.jsonl"
PREVIOUS = ROOT / "docs/evaluation/rag-20261009-before_cases.jsonl"
SAFE_CAS = [
    "64-17-5", "67-56-1", "67-63-0", "67-64-1", "108-88-3", "141-78-6",
    "71-43-2", "71-36-3", "110-54-3", "107-21-1", "100-42-5", "64-19-7",
    "78-93-3", "75-05-8", "75-09-2", "67-66-3", "108-95-2", "95-47-6",
]
FIELD_LABELS = {
    "relative_density": r"(?m)^\s*-\s*Relative density\s*([^\n]+)",
    "vapour_pressure": r"(?m)^\s*-\s*Vapou?r pressure\s*([^\n]+)",
    "autoignition": r"(?m)^\s*-\s*Auto.?ignition temperature\s*([^\n]+)",
    "surface_tension": r"(?m)^\s*(?:-\s*)?Surface tension\s*([^\n]+)",
    "ph": r"(?m)^\s*-\s*pH\s*([^\n]+)",
    "flash_point": r"(?m)^\s*-\s*Flash point\s*([^\n]+)",
    "boiling_point": r"(?m)^\s*-\s*(?:Initial boiling point and boiling range|Boiling point/boiling range)\s*([^\n]+)",
    "melting_point": r"(?m)^\s*-\s*Melting point/freezing point\s*([^\n]+)",
    "molecular_weight": r"(?im)^Molecular Weight:\s*\n\s*([^\n]+)",
}
FIELD_ZH = {"relative_density": "相对密度", "vapour_pressure": "蒸气压", "autoignition": "自燃温度", "surface_tension": "表面张力", "ph": "pH"}


def value_of(row: dict, field: str) -> str | None:
    match = re.search(FIELD_LABELS[field], row["content"], re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    if not re.search(r"\d", value) or re.search(r"no data|not applicable|not determined", value, re.I):
        return None
    # Methods are distinct from the requested numeric property/measurement conditions.
    value = re.split(r"\s+-\s+(?:DIN|closed cup|lit\.)", value, flags=re.I)[0]
    return value


def record(row: dict, name: str, field: str, question: str, category: str) -> dict:
    value = value_of(row, field)
    if not value:
        raise ValueError(f"Missing numeric source fact: {row['cas_no']} {field}")
    return {
        "kind": "answerable", "category": category, "question": question,
        "cas_no": row["cas_no"], "chemical_name": name, "field": field,
        "expected_value": value, "gold_section_ids": [row["id"]],
        "gold_document_id": row["document_id"], "gold_doc_type": row["doc_type"],
        "gold_section_key": row["section_key"],
        "evidence_sha256": hashlib.sha256(row["content"].encode()).hexdigest(),
        "evidence_excerpt": value,
    }


def combine(items: list[dict], question: str, category: str) -> dict:
    first = dict(items[0])
    first.update(
        question=question, category=category, field="multi",
        expected_value=" | ".join(item["expected_value"] for item in items),
        expected_values=[{"field": item["field"], "value": item["expected_value"],
                          "cas_no": item["cas_no"], "chemical_name": item["chemical_name"]} for item in items],
        target_cas=list(dict.fromkeys(item["cas_no"] for item in items)),
        gold_section_ids=list(dict.fromkeys(item["gold_section_ids"][0] for item in items)),
        evidence_sha256_by_section={str(item["gold_section_ids"][0]): item["evidence_sha256"] for item in items},
        gold_doc_type=items[0]["gold_doc_type"] if len({item["gold_doc_type"] for item in items}) == 1 else "mixed",
    )
    return first


def build(rows: list[dict], previous: list[dict]) -> tuple[list[dict], dict]:
    sections = {}
    names = {}
    for row in rows:
        meta = row.get("meta_json") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        english = meta.get("name_en", "")
        if english.lower() in {"technical data sheet", "safety data sheet", "material safety data sheet"}:
            english = ""
        if row["name_zh"] or english:
            names.setdefault(row["cas_no"], row["name_zh"] or english)
        sections.setdefault((row["cas_no"], row["doc_type"], row["section_no"]), row)

    def source(cas, kind="msds"):
        return sections[(cas, kind, 9 if kind == "msds" else 1)]

    def fact(cas, field, question="", category="internal"):
        return record(source(cas, "tds" if field == "molecular_weight" else "msds"), names[cas], field, question, category)

    cases = []
    # 24 new-field questions; rotate starting chemical rather than repeating one easy document.
    for offset, field in enumerate(("relative_density", "vapour_pressure", "autoignition", "surface_tension")):
        ordered = SAFE_CAS[offset * 3:] + SAFE_CAS[:offset * 3]
        eligible = [cas for cas in ordered if (cas, "msds", 9) in sections and value_of(source(cas), field)]
        if len(eligible) < 6:
            raise ValueError(f"Insufficient source facts: {field}")
        for position, cas in enumerate(eligible[:6]):
            name, zh = names[cas], FIELD_ZH[field]
            questions = (
                f"按 {name}（CAS {cas}）的安全资料，{zh}记载为何值？请保留原文单位及测量条件。",
                f"需要核对 {name} 的{zh}，请读取 MSDS 第9节并给出数值和条件。",
                f"查询 CAS {cas} 的{zh}资料，摘录数值、单位及对应条件，不做换算。",
            )
            cases.append(fact(cas, field, questions[position % 3], "new_field_" + field))

    # 12 genuinely different name forms, without explicit CAS in the query.
    alias_queries = [
        ("64-17-5", "ETHYL ALCOHOL", "flash_point", "闪点"),
        ("78-93-3", "MEK", "boiling_point", "初沸点"),
        ("67-56-1", "METHANOL", "flash_point", "闪点"),
        ("67-63-0", "Isopropyl alcohol", "boiling_point", "沸点"),
        ("71-36-3", "1-Butanol", "flash_point", "闪点"),
        ("71-43-2", "BENZENE", "boiling_point", "沸点"),
        ("100-42-5", "Styrene", "flash_point", "闪点"),
        ("107-21-1", "Ethylene glycol", "boiling_point", "沸点"),
        ("108-88-3", "TOLUENE", "flash_point", "闪点"),
        ("141-78-6", "Ethyl acetate", "boiling_point", "沸点"),
        ("67-64-1", "ACETONE", "flash_point", "闪点"),
        ("75-09-2", "Dichloromethane", "boiling_point", "沸点"),
    ]
    for cas, alias, field, zh in alias_queries:
        cases.append(fact(cas, field, f"采购资料写的是 {alias}；请从安全数据表核对其{zh}及单位。", "alias_question"))

    # 8 new combinations of source types and facts.
    density_cas = [cas for cas in SAFE_CAS if value_of(source(cas), "relative_density")]
    cross_cas = [cas for cas in density_cas if (cas, "tds", 1) in sections and value_of(source(cas, "tds"), "molecular_weight")]
    if len(cross_cas) < 8 or len(density_cas) < 8:
        raise ValueError("Insufficient cross-source/comparison evidence")
    for cas in cross_cas[:8]:
        items = [fact(cas, "relative_density"), fact(cas, "molecular_weight")]
        cases.append(combine(items, f"核对 {names[cas]}：安全资料的相对密度和 TDS 的分子量各是多少？请分别标明来源。", "cross_source_new_fields"))

    # 8 queries with two distinct chemicals and two gold chapters.
    for index in range(8):
        a, b = density_cas[index], density_cas[(index + len(density_cas) // 2) % len(density_cas)]
        items = [fact(a, "relative_density"), fact(b, "relative_density")]
        cases.append(combine(items, f"并列列出 CAS {a} 与 CAS {b} 在 MSDS 第9节中的相对密度及条件，分别注明物质，不要合并成一个数值。", "two_chemical_comparison"))

    # The only parsed chemical absent from the old answerable set: avoid its suspect flash-point line.
    for field, zh in (("relative_density", "相对密度"), ("vapour_pressure", "蒸气压"), ("boiling_point", "初沸点"), ("melting_point", "熔点")):
        cases.append(fact("7664-93-9", field, f"首次核对硫酸（CAS 7664-93-9）：安全数据表第9节的{zh}如何记录？请保留单位及条件。", "new_chemical"))
    ph_cas = [cas for cas in SAFE_CAS if value_of(source(cas), "ph")]
    if len(ph_cas) < 4:
        raise ValueError("Insufficient pH evidence")
    for cas in ph_cas[:4]:
        cases.append(fact(cas, "ph", f"请读取 CAS {cas} 的 MSDS 第9节，核对 pH 数值及测量条件。", "new_field_ph"))

    parsed_cas = {row["cas_no"] for row in rows}
    absent = ["100-41-4", "108-90-7", "109-99-9", "123-91-1", "62-53-3", "108-94-1", "108-10-1", "75-65-0"]
    for cas in absent:
        if not valid_cas_checksum(cas) or cas in parsed_cas:
            raise ValueError(f"Negative target is no longer absent: {cas}")
        cases.append({"kind": "no_evidence", "category": "absent_chemical", "cas_no": cas,
                      "question": f"仅按当前已解析资料，CAS {cas} 的 MSDS 第9节相对密度是多少？如无资料请明确说明。",
                      "gold_section_ids": [], "expected_behavior": "abstain", "reason": "CAS absent from parsed SQL corpus"})
    unavailable = [
        "到货批号 QA-20261009 的实验室实测密度", "某仓库昨天测得的蒸气压",
        "采购批次 NEW-001 的实际杂质含量", "车间当前空气中的实测浓度",
        "编号 SAMPLE-009 样品今日测得的 pH", "这次采购验收测得的实际含水量",
        "某供应商明天交货批次的实测纯度", "具体包装桶在当前仓库的实际温度",
    ]
    for cas, detail in zip(SAFE_CAS[:8], unavailable, strict=True):
        cases.append({"kind": "no_evidence", "category": "unavailable_actual_measurement", "cas_no": cas,
                      "chemical_name": names[cas], "question": f"现有 {names[cas]}（CAS {cas}）文档能给出{detail}吗？请区分资料参考值与实际测量结果。",
                      "gold_section_ids": [], "expected_behavior": "abstain", "reason": "specific real measurement not recorded in generic documents"})
    # Source availability checked against SQL, not presumed from old negative labels.
    missing_sources = [("60-29-7", "msds"), ("60-29-7", "property"), ("7664-93-9", "tds"),
                       ("7664-93-9", "property"), ("75-21-8", "tds"), ("7783-06-4", "tds"),
                       ("78-93-3", "property"), ("108-24-7", "property")]
    for cas, kind in missing_sources:
        if any(row["cas_no"] == cas and row["doc_type"] == kind for row in rows):
            raise ValueError(f"Negative source now exists: {cas} {kind}")
        label = {"msds": "MSDS", "tds": "TDS", "property": "物性页"}[kind]
        cases.append({"kind": "no_evidence", "category": "missing_requested_source", "cas_no": cas,
                      "question": f"只看 CAS {cas} 的{label}，其中的密度是否有记录？请不要用其他来源补答。",
                      "gold_section_ids": [], "expected_behavior": "abstain", "reason": "requested document type absent from parsed SQL corpus"})
    unclear = [
        "请核对这款试剂 MSDS 第9节的相对密度及条件。", "这个溶剂的安全资料中蒸气压是多少？",
        "比较这两种化学品在 TDS 中的分子量。", "这批产品对应的自燃温度记录为何值？",
        "请摘录该试剂的表面张力和测量温度。", "那种物质的安全数据表中 pH 是多少？",
        "请提供上述两种材料的 MSDS 闪点对照。", "这份产品技术资料中的分子式怎样写？",
        "需要确认该物质的 MSDS 运输编号。", "这款溶剂在安全资料里记载的熔点是几度？",
        "那份 MSDS 第14节是什么运输危险类别？", "请读取本品的 TDS 分子量并注明来源。",
        "只按此试剂物性页核对沸点范围。", "对照那两种产品的蒸气压，分别注明单位。",
        "上述材料的密度和自燃温度各是多少？", "需要该化学品在安全资料中的溶解度记录。",
    ]
    for question in unclear:
        cases.append({"kind": "needs_target", "category": "missing_or_multiple_unspecified_targets", "question": question,
                      "cas_no": None, "gold_section_ids": [], "expected_behavior": "clarify", "reason": "no concrete chemical target or prior conversation"})
    old_questions = {case["question"] for case in previous}
    if len(cases) != 100 or len({case["question"] for case in cases}) != 100 or any(case["question"] in old_questions for case in cases):
        raise ValueError("Case count, uniqueness or overlap validation failed")
    for number, case in enumerate(cases, 1):
        case["id"] = f"RAGG-{number:03d}"
    previous_answerable = {case["cas_no"] for case in previous if case["kind"] == "answerable"}
    manifest = {
        "suite": "chemicalops-rag-generalization100-v1", "created_date": "2026-10-09",
        "case_count": len(cases), "kinds": dict(Counter(case["kind"] for case in cases)),
        "categories": dict(Counter(case["category"] for case in cases)),
        "question_overlap_with_previous": 0,
        "new_answerable_cas": sorted({case["cas_no"] for case in cases if case["kind"] == "answerable"} - previous_answerable),
        "annotation": "Rule-generated from parsed SQL sections; evidence hashes frozen before retrieval; not human blind annotation.",
        "scope": "New questions, fields and combinations. Most chemicals/documents overlap with the previous suite; only sulfuric acid is new among answerable chemicals. No production retriever changes in this evaluation.",
        "source_quality": "Original documents may contain inconsistent chemical data. Results measure source-text retrieval, not independently verified physical properties. Suspect ethylene-oxide/hydrogen-sulfide sections and sulfuric-acid flash point excluded from new answer keys.",
    }
    return cases, manifest


def main():
    if OUTPUT.exists():
        raise SystemExit("Frozen suite already exists; use a new version instead of overwriting it")
    engine = create_engine(get_settings().resolved_database_url)
    try:
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(text("""
                SELECT s.id,s.document_id,s.cas_no,s.doc_type,s.section_no,s.section_key,s.content,
                       d.name_zh,d.meta_json FROM ai_document_sections s JOIN ai_documents d ON d.id=s.document_id
                WHERE d.parse_status='PARSED' ORDER BY d.updated_at DESC,s.id DESC
            """)).mappings()]
    finally:
        engine.dispose()
    previous = [json.loads(line) for line in PREVIOUS.read_text(encoding="utf-8").splitlines()]
    cases, manifest = build(rows, previous)
    payload = "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    manifest["gold_sha256"] = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    manifest["previous_gold_sha256"] = hashlib.sha256(PREVIOUS.read_bytes()).hexdigest()
    OUTPUT.with_name(OUTPUT.stem.replace("_cases", "_manifest") + ".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
