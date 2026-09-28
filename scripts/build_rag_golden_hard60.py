"""Build a reproducible harder RAG set from frozen source-backed cases.

This is a synthetic stress set, not an independently annotated blind set.
No database writes are performed.
"""

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/evaluation/rag_golden_200.jsonl"
OUTPUT = ROOT / "docs/evaluation/rag_golden_hard60.jsonl"

SINGLE_CAS = [
    "100-42-5", "107-21-1", "108-24-7", "108-88-3", "108-95-2", "110-54-3",
    "1310-58-3", "1310-73-2", "141-78-6", "50-00-0", "64-17-5", "64-19-7",
    "67-56-1", "67-63-0", "67-64-1", "67-66-3", "71-36-3", "71-43-2",
    "75-05-8", "75-09-2", "7647-14-5", "7681-52-9", "7722-84-1", "95-47-6",
]
DOUBLE_CAS = [
    "100-42-5", "107-21-1", "108-88-3", "108-95-2", "110-54-3", "141-78-6",
    "64-17-5", "64-19-7", "67-56-1", "67-63-0", "71-36-3", "71-43-2",
]
CROSS_CAS = [
    "100-42-5", "108-88-3", "108-95-2", "110-54-3", "141-78-6", "64-17-5",
    "64-19-7", "67-56-1", "67-63-0", "67-64-1", "71-36-3", "71-43-2",
]
FIELD_QUESTIONS = {
    "flash_point": "查现有资料，{name} 的闪点记录是多少？请附单位。",
    "boiling_point": "{name} 的初沸点或沸程，在安全数据表里写成多少？",
    "melting_point": "请从资料中找出 {name} 的熔点数值。",
    "molecular_formula": "库内产品资料把 {name} 的分子式写成什么？",
    "molecular_weight": "{name} 的产品资料列出的分子量是多少？",
}
SCENARIOS = [
    "现有资料能确定 {name} 在某车间泄漏十分钟后，工人实际吸入的浓度是多少吗？请给出具体数值。",
    "请告诉我 {name} 的 2027 年批次 CO-2027 实测纯度，不要给规格下限。",
    "一桶 {name} 明天在仓库存放时的实际桶内压力是多少？请直接给数值。",
    "只凭库内资料，能确定某人接触 {name} 后一定会在几分钟内出现症状吗？请给确定时间。",
]


def source_record(item: dict) -> dict:
    return {key: item[key] for key in (
        "cas_no", "chemical_name", "field", "expected_value", "gold_section_ids",
        "gold_document_id", "gold_doc_type", "gold_section_key", "evidence_sha256", "evidence_excerpt",
    )}


def combined(items: list[dict], question: str, category: str) -> dict:
    ids = list(dict.fromkeys(section_id for item in items for section_id in item["gold_section_ids"]))
    hashes = {str(item["gold_section_ids"][0]): item["evidence_sha256"] for item in items}
    first = source_record(items[0])
    first.update({
        "kind": "answerable", "category": category, "question": question,
        "field": "multi", "expected_value": " | ".join(item["expected_value"] for item in items),
        "expected_values": [{"field": item["field"], "value": item["expected_value"]} for item in items],
        "gold_section_ids": ids, "evidence_sha256_by_section": hashes,
        "gold_doc_type": items[0]["gold_doc_type"] if len({item["gold_doc_type"] for item in items}) == 1 else "mixed",
    })
    return first


def main() -> None:
    source = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    index = defaultdict(dict)
    for item in source:
        if item["kind"] == "answerable":
            index[item["cas_no"]][(item["gold_doc_type"], item["field"])] = item

    cases = []
    field_order = ["flash_point", "molecular_formula", "melting_point", "boiling_point", "molecular_weight"]
    for position, cas in enumerate(SINGLE_CAS):
        options = index[cas]
        preferred = field_order[position % len(field_order):] + field_order[:position % len(field_order)]
        item = next(options[key] for field in preferred for key in (("msds", field), ("property", field), ("tds", field)) if key in options)
        case = source_record(item)
        question = FIELD_QUESTIONS[item["field"]].format(name=item["chemical_name"])
        if item["field"] == "melting_point":
            source_name = "物性页" if item["gold_doc_type"] == "property" else "安全数据表"
            question = f"请从 {item['chemical_name']} 的{source_name}中找出熔点数值。"
        case.update(kind="answerable", category="natural_single", question=question)
        cases.append(case)

    for cas in DOUBLE_CAS:
        flash = index[cas][("msds", "flash_point")]
        boiling = index[cas][("msds", "boiling_point")]
        name = flash["chemical_name"]
        cases.append(combined([flash, boiling], f"把 {name} 的闪点和初沸点一起列出来，并分别注明单位。", "same_source_two_facts"))

    for cas in CROSS_CAS:
        flash = index[cas][("msds", "flash_point")]
        weight = index[cas][("tds", "molecular_weight")]
        name = flash["chemical_name"]
        cases.append(combined([flash, weight], f"结合 {name} 的安全资料和产品技术资料，闪点与分子量分别是多少？", "cross_source_two_facts"))

    for position, cas in enumerate(SINGLE_CAS[:12]):
        name = next(iter(index[cas].values()))["chemical_name"]
        cases.append({
            "kind": "no_evidence", "category": "insufficient_scenario",
            "question": SCENARIOS[position % len(SCENARIOS)].format(name=name),
            "cas_no": cas, "chemical_name": name, "gold_section_ids": [],
            "expected_behavior": "abstain", "reason": "source documents cannot determine this actual or future outcome",
        })

    assert len(cases) == 60 and len({case["question"] for case in cases}) == 60
    assert not ({case["question"] for case in cases} & {case["question"] for case in source})
    for number, case in enumerate(cases, 1):
        case["id"] = f"RAGH-{number:03d}"
    OUTPUT.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUTPUT}")
    print({category: sum(case["category"] == category for case in cases) for category in (
        "natural_single", "same_source_two_facts", "cross_source_two_facts", "insufficient_scenario",
    )})


if __name__ == "__main__":
    main()
