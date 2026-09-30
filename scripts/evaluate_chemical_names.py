"""Replay target identification on the fixed mixed-200 corpus, without model calls."""
import asyncio
import json
import hashlib
import sys
from pathlib import Path
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.db import SessionLocal
from app.modules.doc_kb.model import AiDocumentSection
from app.modules.doc_kb.retrieve import resolve_doc_targets

async def main():
    inputs = ROOT / "docs/evaluation/rag_golden_mixed200.jsonl"
    rows = [json.loads(line) for line in inputs.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with SessionLocal() as db:
        cas_by_section = dict(db.execute(select(AiDocumentSection.id, AiDocumentSection.cas_no)).all())
        for row in rows:
            if row["kind"] != "answerable":
                continue
            section_ids = row.get("gold_section_ids", [])
            if not section_ids or any(section_id not in cas_by_section for section_id in section_ids):
                raise RuntimeError(f"Corpus evidence missing: {row['id']}")
            expected = sorted({cas_by_section[section_id] for section_id in section_ids})
            targets = await resolve_doc_targets(db, row["question"])
            results.append({"id":row["id"], "question":row["question"], "expected_cas":expected, "resolved_cas":targets, "passed":set(expected) == set(targets)})
    summary = {"scope":"target identification only; no retrieval or answer generation", "total":len(results), "passed":sum(x["passed"] for x in results), "failed":[x for x in results if not x["passed"]]}
    old_results = [json.loads(line) for line in (ROOT / "docs/evaluation/rag_eval_results_mixed200.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    unresolved_ids = {row["id"] for row in old_results if row.get("kind") == "answerable" and row.get("intent_reason") == "chemical_target_unresolved"}
    summary["input_sha256"] = hashlib.sha256(inputs.read_bytes()).hexdigest()
    summary["previous_unresolved_total"] = len(unresolved_ids)
    summary["previous_unresolved_now_passed"] = sum(row["passed"] and row["id"] in unresolved_ids for row in results)
    output = ROOT / "docs/evaluation/chemical_name_regression_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["failed"] else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
