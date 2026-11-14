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


def test_generation_error_counts_in_accuracy_denominator_and_records_run_meta(tmp_path, monkeypatch):
    """RAG 生成阶段超时/出错不得被剔除出准确率分母，且保留断点与基础设施 run_meta。"""
    import asyncio
    import httpx
    from contextlib import contextmanager
    from sqlalchemy import select

    cases = [
        {
            "id": "rag-ok", "kind": "answerable", "cas_no": "64-17-5", "chemical_name": "Ethanol",
            "gold_doc_type": "msds", "gold_section_ids": [1], "gold_document_id": 1,
            "evidence_sha256": hashlib.sha256(b"flash 13 C").hexdigest(),
            "question": "flash point", "field": "flash_point", "expected_value": "13 C",
        },
        {
            "id": "rag-timeout", "kind": "answerable", "cas_no": "64-17-5", "chemical_name": "Ethanol",
            "gold_doc_type": "msds", "gold_section_ids": [1], "gold_document_id": 1,
            "evidence_sha256": hashlib.sha256(b"flash 13 C").hexdigest(),
            "question": "boiling point", "field": "boiling_point", "expected_value": "78 C",
        },
    ]
    gold_path = tmp_path / "gold.jsonl"
    results_path = tmp_path / "results.jsonl"
    summary_path = tmp_path / "summary.json"
    gold_path.write_text("\n".join("{}", *[]), encoding="utf-8")
    monkeypatch.setattr(evaluation, "GOLD", gold_path)
    monkeypatch.setattr(evaluation, "RESULTS", results_path)
    monkeypatch.setattr(evaluation, "SUMMARY", summary_path)

    class _FakeDb:
        def get(self, _model, _id):
            return SimpleNamespace(id=1, content="flash 13 C", doc_type="msds")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(evaluation, "create_engine", lambda _url: SimpleNamespace(dispose=lambda: None))
    monkeypatch.setattr(evaluation, "Session", lambda _engine: _FakeDb())
    monkeypatch.setattr(evaluation, "embed_texts", lambda texts, _s: _async_val([[1.0] for _ in texts]))
    monkeypatch.setattr(evaluation, "_classify_chat_intent", lambda _db, _q: _async_val(SimpleNamespace(intent="doc", reason="ok")))
    monkeypatch.setattr(
        evaluation.retrieve_module,
        "retrieve_sections",
        lambda _db, _q: _async_val([SimpleNamespace(id=1, doc_type="msds")]),
    )
    monkeypatch.setattr(evaluation.retrieve_module, "build_doc_context", lambda _hits: ("ctx", []))

    seen_settings = []

    async def fake_chat(req, settings, **_kwargs):
        seen_settings.append(settings.llm_timeout_seconds)
        if "boiling" in req.messages[0].content:
            raise httpx.ReadTimeout("timeout")
        return SimpleNamespace(answer="13 C，来源：Ethanol", message=SimpleNamespace(content=""), model="mock")

    monkeypatch.setattr(evaluation, "chat", fake_chat)

    rows = asyncio.run(evaluation.evaluate(cases, with_generation=True, concurrency=2, force=True))
    summary = evaluation.summarize(cases, rows)
    by_id = {r["id"]: r for r in rows}

    assert seen_settings and all(t >= 120 for t in seen_settings)
    assert "answer" not in by_id["rag-timeout"]
    assert by_id["rag-timeout"]["fact_match"] is False
    assert by_id["rag-timeout"]["run_meta"]["error"]["class"] == "AMBIGUOUS_TIMEOUT"
    assert summary["answer_fact_accuracy"] == 0.5
    assert summary["source_grounded_fact_accuracy"] == 0.5
    assert summary["generation_errors"] == 1


async def _async_val(val):
    return val
