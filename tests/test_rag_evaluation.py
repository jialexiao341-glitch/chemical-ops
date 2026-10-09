"""Frozen RAG evidence migration must preserve facts and reject ambiguous replacements."""

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location("rag_evaluation", Path(__file__).resolve().parents[1] / "scripts/evaluate_rag.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def _case():
    return {
        "id": "frozen-case", "kind": "answerable", "cas_no": "64-17-5",
        "gold_doc_type": "msds", "gold_section_ids": [10], "gold_document_id": 1,
        "evidence_sha256": hashlib.sha256(b"unchanged evidence").hexdigest(),
        "question": "What is the flash point?", "expected_value": "13 C",
    }


class EvidenceDatabase:
    def __init__(self, candidates, existing=None):
        self.candidates = candidates
        self.existing = existing

    def get(self, _model, _id):
        return self.existing

    def scalars(self, _query):
        return self.candidates


def _section(section_id=20, content="unchanged evidence", doc_type="msds"):
    return SimpleNamespace(id=section_id, document_id=2, content=content, doc_type=doc_type)


def test_rebind_only_changes_identifiers_and_does_not_mutate_original():
    original = _case()
    rebound, mapping = evaluation.rebind_missing_evidence([original], EvidenceDatabase([_section()]))
    assert original["gold_section_ids"] == [10]
    assert rebound[0]["gold_section_ids"] == [20]
    assert rebound[0]["gold_document_id"] == 2
    assert rebound[0]["question"] == original["question"]
    assert rebound[0]["expected_value"] == original["expected_value"]
    assert rebound[0]["evidence_sha256"] == original["evidence_sha256"]
    assert mapping[0]["old_section_id"] == 10


@pytest.mark.parametrize("candidates", [
    [_section(content="changed evidence")],
    [_section(doc_type="tds")],
    [_section(), _section(21)],
    [],
])
def test_rebind_rejects_changed_wrong_source_missing_or_duplicate_evidence(candidates):
    with pytest.raises(RuntimeError, match="uniquely rebind"):
        evaluation.rebind_missing_evidence([_case()], EvidenceDatabase(candidates))


def test_rebind_does_not_replace_existing_evidence_even_when_content_changed():
    rebound, mapping = evaluation.rebind_missing_evidence(
        [_case()], EvidenceDatabase([_section()], existing=_section(10, "changed")),
    )
    assert rebound[0]["gold_section_ids"] == [10]
    assert not mapping  # Evaluation's separate hash check must reject the changed row.


def test_checkpoint_replace_failure_preserves_previous_result(tmp_path, monkeypatch):
    destination = tmp_path / "results.jsonl"
    evaluation.write_jsonl(destination, [{"id": "previous"}])

    def fail_replace(_self, _target):
        raise PermissionError("Destination temporarily locked")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        evaluation.write_jsonl(destination, [{"id": "new"}])
    assert evaluation.read_jsonl(destination) == [{"id": "previous"}]
    assert list(tmp_path.iterdir()) == [destination]


def test_qualitative_ph_cannot_pass_by_matching_only_its_temperature():
    case = {"field": "ph", "expected_value": "neutral at 20 °C"}
    assert not evaluation.fact_match(case, "测量温度是20 °C，pH未知")
    assert evaluation.fact_match(case, "pH记录为中性，条件为20 °C")
