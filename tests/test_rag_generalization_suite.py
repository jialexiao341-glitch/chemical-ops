"""Guard the new frozen suite against leakage, lost evidence and missing coverage."""

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "docs/evaluation/rag-generalization-100-20261009_cases.jsonl"


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_new_suite_is_frozen_unique_and_does_not_reuse_old_questions():
    cases = _read(CASES)
    previous = _read(ROOT / "docs/evaluation/rag-20261009-before_cases.jsonl")
    manifest = json.loads(CASES.with_name(CASES.name.replace("_cases.jsonl", "_manifest.json")).read_text(encoding="utf-8"))
    assert len(cases) == len({case["id"] for case in cases}) == len({case["question"] for case in cases}) == 100
    assert not {case["question"] for case in cases}.intersection(case["question"] for case in previous)
    assert Counter(case["kind"] for case in cases) == {"answerable": 60, "no_evidence": 24, "needs_target": 16}
    assert manifest["gold_sha256"] == hashlib.sha256(CASES.read_bytes()).hexdigest()


def test_multi_chemical_and_source_cases_retain_all_evidence():
    cases = _read(CASES)
    comparisons = [case for case in cases if case["category"] == "two_chemical_comparison"]
    assert len(comparisons) == 8
    for case in comparisons:
        assert len(set(case["target_cas"])) == len(case["gold_section_ids"]) == 2
        assert set(case["evidence_sha256_by_section"]) == {str(section) for section in case["gold_section_ids"]}
        assert {value["cas_no"] for value in case["expected_values"]} == set(case["target_cas"])
    cross_source = [case for case in cases if case["category"] == "cross_source_new_fields"]
    assert len(cross_source) == 8
    assert all(case["gold_doc_type"] == "mixed" and len(case["gold_section_ids"]) == 2 for case in cross_source)


def test_new_suite_covers_unseen_fields_and_keeps_negative_cases_evidence_free():
    cases = _read(CASES)
    answerable = [case for case in cases if case["kind"] == "answerable"]
    assert {"relative_density", "vapour_pressure", "autoignition", "surface_tension", "ph"}.issubset(
        {case["field"] for case in answerable}
    )
    assert all(case["gold_section_ids"] and len(case["evidence_sha256"]) == 64 for case in answerable)
    assert all(not case["gold_section_ids"] for case in cases if case["kind"] != "answerable")
    assert all(case["cas_no"] is None for case in cases if case["kind"] == "needs_target")


def test_builder_rejects_numbers_that_are_not_measured_values():
    spec = importlib.util.spec_from_file_location("rag_suite_builder", ROOT / "scripts/build_rag_generalization100.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    unavailable = {"content": "- Autoignition temperature No data available at 20 °C"}
    assert builder.value_of(unavailable, "autoignition") is None
    measured = {"content": "- Vapour pressure 0,57 hPa at 19,6 °C\n- Vapour density1,6"}
    assert builder.value_of(measured, "vapour_pressure") == "0,57 hPa at 19,6 °C"
