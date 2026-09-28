"""Freeze a reproducible mixed 200-case RAG suite (140 easy + 60 hard)."""

import hashlib
import json
import random
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs/evaluation"
EASY = DIRECTORY / "rag_golden_200.jsonl"
HARD = DIRECTORY / "rag_golden_hard60.jsonl"
OUTPUT = DIRECTORY / "rag_golden_mixed200.jsonl"
MANIFEST = DIRECTORY / "rag_golden_mixed200_manifest.json"
SEED = 20260928


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    easy, hard = read_jsonl(EASY), read_jsonl(HARD)
    if len(easy) != 200 or len(hard) != 60:
        raise RuntimeError("source suites must contain 200 easy and 60 hard cases")
    rng = random.Random(SEED)
    selected = rng.sample(easy, 140)
    selected_ids = [case["id"] for case in selected]
    rows = [
        {**case, "category": f"easy_{case['kind']}", "sample_origin": "easy200"}
        for case in selected
    ] + [{**case, "sample_origin": "hard60"} for case in hard]
    rng.shuffle(rows)
    if len(rows) != 200 or len({case["id"] for case in rows}) != 200:
        raise RuntimeError("mixed suite must have 200 unique case IDs")
    OUTPUT.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in rows) + "\n", encoding="utf-8")
    manifest = {
        "seed": SEED,
        "easy_source": EASY.name, "easy_source_sha256": sha256(EASY),
        "hard_source": HARD.name, "hard_source_sha256": sha256(HARD),
        "selected_easy_ids": selected_ids,
        "mixed_sha256": sha256(OUTPUT),
        "counts_by_origin": dict(Counter(case["sample_origin"] for case in rows)),
        "counts_by_kind": dict(Counter(case["kind"] for case in rows)),
        "counts_by_category": dict(Counter(case["category"] for case in rows)),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} cases to {OUTPUT}")
    print("Kinds:", manifest["counts_by_kind"])
    print("Categories:", manifest["counts_by_category"])


if __name__ == "__main__":
    main()
