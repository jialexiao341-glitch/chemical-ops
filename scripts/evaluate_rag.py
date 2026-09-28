"""Evaluate the frozen ChemicalOps document RAG set without writing business data.

Runs the same intent, retrieval, context, and model functions used by the chat path.
Results are checkpointed so a failed model call can be resumed without repeating it.
"""

import argparse
import asyncio
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.modules.ai.intent import Intent  # noqa: E402
from app.modules.ai.schema import AIChatMessage, AIChatRequest  # noqa: E402
from app.modules.ai.service import _classify_chat_intent, chat  # noqa: E402
from app.modules.doc_kb import retrieve as retrieve_module  # noqa: E402
from app.modules.doc_kb.embedding import embed_texts  # noqa: E402
from app.modules.doc_kb.model import AiDocumentSection  # noqa: E402
from app.modules.doc_kb.retrieve import no_doc_hits_reply  # noqa: E402


GOLD = ROOT / "docs" / "evaluation" / "rag_golden_mixed200.jsonl"
RESULTS = ROOT / "docs" / "evaluation" / "rag_eval_results_mixed200.jsonl"
SUMMARY = ROOT / "docs" / "evaluation" / "rag_eval_summary_mixed200.json"
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
REFUSAL_WORDS = ("未收录", "没有", "无法", "未提供", "找不到", "未知", "资料不足", "不包含", "未见", "不能确定", "缺少", "未查到")
CLARIFY_WORDS = ("请提供", "请说明", "哪种", "具体", "化学品名称", "CAS", "物质名称")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def number_tokens(text: str) -> list[str]:
    text = text.translate(str.maketrans({"−": "-", "–": "-", "—": "-", "，": ".", "．": "."}))
    values = re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?![\w])", text)
    result = []
    for value in values:
        value = value.replace(",", ".")
        if re.fullmatch(r"\d\.\d{3}", value) and int(value[0]) >= 1:
            value = value.replace(".", "")
        try:
            result.append(str(float(value)).rstrip("0").rstrip(".") if "." in value else str(int(value)))
        except ValueError:
            continue
    return result


def fact_match(case: dict, answer: str) -> bool:
    if case.get("expected_values"):
        return all(fact_match({"field": item["field"], "expected_value": item["value"]}, answer)
                   for item in case["expected_values"])
    expected = case["expected_value"]
    if case["field"] == "molecular_formula":
        formula = re.sub(r"[^A-Za-z0-9]", "", expected.translate(SUBSCRIPTS)).lower()
        answer_normal = answer.translate(SUBSCRIPTS)
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(formula)}(?![A-Za-z0-9])", answer_normal.lower()))
    expected_numbers = number_tokens(expected.split("°C", 1)[0])
    actual_numbers = number_tokens(answer)
    return bool(expected_numbers) and all(number in actual_numbers for number in expected_numbers)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(fraction * len(ordered)) - 1], 3)


async def evaluate(cases: list[dict], *, with_generation: bool, concurrency: int, force: bool) -> list[dict]:
    settings = get_settings()
    engine = create_engine(settings.resolved_database_url)
    results = {} if force else {row["id"]: row for row in read_jsonl(RESULTS)}
    vectors: dict[str, list[float]] = {}
    questions = [case["question"] for case in cases if case["kind"] != "needs_target"]
    for start in range(0, len(questions), 10):
        batch = questions[start:start + 10]
        for question, vector in zip(batch, await embed_texts(batch, settings), strict=True):
            vectors[question] = vector

    async def cached_embed(texts: list[str], _settings=None) -> list[list[float]]:
        missing = [item for item in texts if item not in vectors]
        if missing:
            for item, vector in zip(missing, await original_embed(missing, settings), strict=True):
                vectors[item] = vector
        return [vectors[text] for text in texts]

    original_embed = retrieve_module.embed_texts
    retrieve_module.embed_texts = cached_embed
    pending_generation: list[tuple[dict, dict, str]] = []
    try:
        with Session(engine) as db:
            for case in cases:
                if case["kind"] == "answerable":
                    evidence_hashes = case.get("evidence_sha256_by_section") or {
                        str(case["gold_section_ids"][0]): case["evidence_sha256"]
                    }
                    for section_id, expected_hash in evidence_hashes.items():
                        section = db.get(AiDocumentSection, int(section_id))
                        if section is None or hashlib.sha256(section.content.encode("utf-8")).hexdigest() != expected_hash:
                            raise RuntimeError(f"Gold evidence changed: {case['id']} section {section_id}")
                prior = results.get(case["id"])
                if prior and (not with_generation or "answer" in prior):
                    continue
                intent = await _classify_chat_intent(db, case["question"])
                started = perf_counter()
                hits = [] if intent.reason == "chemical_target_unresolved" else await retrieve_module.retrieve_sections(db, case["question"])
                elapsed = perf_counter() - started
                hit_ids = [hit.id for hit in hits]
                gold_ids = set(case["gold_section_ids"])
                relevant_ranks = [index for index, hit_id in enumerate(hit_ids, 1) if hit_id in gold_ids]
                row = {
                    "id": case["id"], "kind": case["kind"], "question": case["question"],
                    "intent": str(intent.intent), "intent_reason": intent.reason,
                    "gold_section_ids": case["gold_section_ids"], "retrieved_section_ids": hit_ids,
                    "retrieved_doc_types": [hit.doc_type for hit in hits],
                    "retrieval_seconds": round(elapsed, 3),
                    "recall_at_6": len(relevant_ranks) / len(gold_ids) if gold_ids else None,
                    "precision_at_6": len(relevant_ranks) / 6 if gold_ids else None,
                    "rr_at_6": 1 / relevant_ranks[0] if relevant_ranks else (0.0 if gold_ids else None),
                    "ndcg_at_6": (sum(1 / math.log2(rank + 1) for rank in relevant_ranks) /
                                  sum(1 / math.log2(rank + 1) for rank in range(1, min(len(gold_ids), 6) + 1))) if gold_ids else None,
                    "expected_value": case.get("expected_value"),
                }
                if not hits:
                    row["answer"] = "请提供准确的化学品名称或 CAS 号。" if case["kind"] == "needs_target" else no_doc_hits_reply(case["question"])
                    row["model"] = "rule-based"
                elif with_generation:
                    context, _citations = retrieve_module.build_doc_context(hits)
                    pending_generation.append((case, row, context))
                results[case["id"]] = row
                if len(results) % 10 == 0:
                    write_jsonl(RESULTS, [results[c["id"]] for c in cases if c["id"] in results])
            write_jsonl(RESULTS, [results[c["id"]] for c in cases if c["id"] in results])
    finally:
        retrieve_module.embed_texts = original_embed
        engine.dispose()

    if with_generation and pending_generation:
        semaphore = asyncio.Semaphore(concurrency)

        async def generate(case: dict, row: dict, context: str) -> None:
            async with semaphore:
                started = perf_counter()
                try:
                    reply = await chat(AIChatRequest(messages=[AIChatMessage(role="user", content=case["question"])]),
                                       settings, attachment_context=[context])
                    row["answer"] = reply.answer or reply.message.content
                    row["model"] = reply.model
                    row["generation_seconds"] = round(perf_counter() - started, 3)
                except Exception as exc:
                    row["generation_error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
                results[case["id"]] = row
                write_jsonl(RESULTS, [results[c["id"]] for c in cases if c["id"] in results])

        await asyncio.gather(*(generate(*item) for item in pending_generation))

    for case in cases:
        row = results.get(case["id"])
        if row is None or "answer" not in row:
            continue
        answer = row["answer"]
        if case["kind"] == "answerable":
            row["fact_match"] = fact_match(case, answer)
            row["text_citation_present"] = ("来源" in answer or "source" in answer.lower()) and case["chemical_name"].lower() in answer.lower()
        elif case["kind"] == "no_evidence":
            row["abstained"] = any(word in answer for word in REFUSAL_WORDS)
        else:
            row["requested_target"] = any(word in answer for word in CLARIFY_WORDS)
    ordered = [results[c["id"]] for c in cases if c["id"] in results]
    write_jsonl(RESULTS, ordered)
    return ordered


def summarize(cases: list[dict], rows: list[dict]) -> dict:
    by_id = {r["id"]: r for r in rows}
    answerable = [by_id[c["id"]] for c in cases if c["kind"] == "answerable" and c["id"] in by_id]
    negatives = [by_id[c["id"]] for c in cases if c["kind"] == "no_evidence" and c["id"] in by_id]
    unclear = [by_id[c["id"]] for c in cases if c["kind"] == "needs_target" and c["id"] in by_id]

    def mean(key: str, subset: list[dict]) -> float | None:
        values = [float(row[key]) for row in subset if row.get(key) is not None]
        return round(statistics.mean(values), 4) if values else None

    report = {
        "case_count": len(cases), "evaluated_count": len(rows), "answerable_count": len(answerable),
        "no_evidence_count": len(negatives), "needs_target_count": len(unclear),
        "retrieval": {key: mean(key, answerable) for key in ("recall_at_6", "precision_at_6", "rr_at_6", "ndcg_at_6")},
        "answer_fact_accuracy": mean("fact_match", answerable),
        "source_grounded_fact_accuracy": round(
            sum(bool(r.get("fact_match")) and r.get("recall_at_6") == 1 for r in answerable) / len(answerable), 4
        ) if answerable else None,
        "answer_text_citation_rate": mean("text_citation_present", answerable),
        "no_evidence_abstention_rate": mean("abstained", negatives),
        "needs_target_clarification_rate": mean("requested_target", unclear),
        "generation_errors": sum("generation_error" in r for r in rows),
        "retrieval_post_embedding_p50_seconds": percentile([r["retrieval_seconds"] for r in rows], .5),
        "retrieval_post_embedding_p95_seconds": percentile([r["retrieval_seconds"] for r in rows], .95),
        "generation_p95_seconds": percentile([r["generation_seconds"] for r in rows if "generation_seconds" in r], .95),
        "failed_fact_case_ids": [r["id"] for r in answerable if r.get("fact_match") is False],
        "missed_retrieval_case_ids": [r["id"] for r in answerable if r.get("recall_at_6") == 0],
        "retrieval_by_gold_doc_type": {
            doc_type: {
                "cases": sum(c["kind"] == "answerable" and c["gold_doc_type"] == doc_type for c in cases),
                "hits_at_6": sum(c["kind"] == "answerable" and c["gold_doc_type"] == doc_type and
                                 bool(by_id[c["id"]].get("recall_at_6")) for c in cases if c["id"] in by_id),
            }
            for doc_type in ("msds", "property", "tds")
        },
        "by_category": {
            category: {
                "cases": sum(c.get("category") == category for c in cases),
                "full_recall_at_6": sum(c.get("category") == category and
                                        by_id[c["id"]].get("recall_at_6") == 1 for c in cases if c["id"] in by_id),
                "fact_match": sum(c.get("category") == category and
                                  bool(by_id[c["id"]].get("fact_match")) for c in cases if c["id"] in by_id),
                "abstained": sum(c.get("category") == category and
                                 bool(by_id[c["id"]].get("abstained")) for c in cases if c["id"] in by_id),
            }
            for category in sorted({c["category"] for c in cases if c.get("category")})
        },
        "scope": "Document RAG only. Fact accuracy checks the expected value; source-grounded accuracy also requires the requested section. Embeddings were batched and cached, so retrieval timing excludes embedding. Text citation rate is a presence proxy, not citation correctness or full faithfulness.",
    }
    SUMMARY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    global GOLD, RESULTS, SUMMARY
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("200", "hard60", "mixed200"), default="mixed200")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="discard checkpoints and run all cases again")
    args = parser.parse_args()
    if args.suite == "200":
        GOLD = ROOT / "docs" / "evaluation" / "rag_golden_200.jsonl"
        RESULTS = ROOT / "docs" / "evaluation" / "rag_eval_results_200.jsonl"
        SUMMARY = ROOT / "docs" / "evaluation" / "rag_eval_summary_200.json"
    elif args.suite == "hard60":
        GOLD = ROOT / "docs" / "evaluation" / "rag_golden_hard60.jsonl"
        RESULTS = ROOT / "docs" / "evaluation" / "rag_eval_results_hard60.jsonl"
        SUMMARY = ROOT / "docs" / "evaluation" / "rag_eval_summary_hard60.json"
    elif args.suite == "mixed200":
        GOLD = ROOT / "docs" / "evaluation" / "rag_golden_mixed200.jsonl"
        RESULTS = ROOT / "docs" / "evaluation" / "rag_eval_results_mixed200.jsonl"
        SUMMARY = ROOT / "docs" / "evaluation" / "rag_eval_summary_mixed200.json"
    if args.concurrency < 1 or args.concurrency > 8:
        raise SystemExit("concurrency must be 1..8")
    cases = read_jsonl(GOLD)
    expected_count = 60 if args.suite == "hard60" else 200
    if len(cases) != expected_count or len({case["id"] for case in cases}) != expected_count:
        raise SystemExit(f"expected {args.suite} unique golden cases")
    rows = asyncio.run(evaluate(cases, with_generation=not args.retrieval_only, concurrency=args.concurrency, force=args.force))
    print(json.dumps(summarize(cases, rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
