"""技术资料流水线的入参约束。"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.app.modules.jobs.schema import TechnicalDocumentPipelineCreate, TechnicalDocumentPreviewRead
from backend.app.modules.jobs import technical_documents


def test_pipeline_accepts_only_supported_document_types():
    request = TechnicalDocumentPipelineCreate(cas_no="64-17-5", doc_types=["msds", "tds"])
    assert request.doc_types == ["msds", "tds"]

    for doc_types in ([], ["property"], ["msds", "msds"]):
        with pytest.raises(ValidationError):
            TechnicalDocumentPipelineCreate(cas_no="64-17-5", doc_types=doc_types)


def test_pipeline_requires_a_valid_cas_number():
    with pytest.raises(ValidationError):
        TechnicalDocumentPipelineCreate(cas_no="not-a-cas", doc_types=["msds"])


def test_fetch_requires_each_requested_type_to_be_available_in_minio():
    assert technical_documents.missing_requested_types(
        ["msds", "tds"],
        [{"doc_type": "msds"}],
    ) == ["tds"]
    assert technical_documents.missing_requested_types(["tds"], []) == ["tds"]
    assert technical_documents.missing_requested_types(
        ["msds", "tds"],
        [{"doc_type": "msds"}, {"doc_type": "tds"}],
    ) == []


def test_queue_waiting_and_retrying_are_active_without_recent_run_limit(monkeypatch):
    """排队和重试参与 CAS 互斥，不以固定最近 100 条作为安全边界。"""
    from app.modules.jobs import technical_documents as queued_documents
    class Database:
        def scalars(self, statement):
            sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "LIMIT" not in sql and "QUEUED" in sql and "RETRYING" in sql
            return type("Rows", (), {"all": lambda self: [type("Run", (), {"result_json": {"cas_no": "64-17-5"}})()]})()
    assert queued_documents.has_active_run(Database(), "64-17-5")


def test_partial_fetch_is_recorded_as_failed_with_available_files_preserved(monkeypatch):
    class Run:
        run_id = "run-1"
        attempt_count = 0
        status = "RUNNING"
        result_json = None
        error_type = None
        finished_at = None

    class Database:
        run = Run()

        def scalar(self, _statement):
            return self.run

        def commit(self):
            pass

        def rollback(self):
            pass

        def expire_all(self):
            pass

        def close(self):
            pass

    database = Database()
    monkeypatch.setattr(technical_documents, "SessionLocal", lambda: database)
    monkeypatch.setattr(technical_documents.subprocess, "run", lambda *args, **kwargs: type("Result", (), {
        "returncode": 0,
        "stdout": "uploaded MSDS",
        "stderr": "",
    })())
    monkeypatch.setattr(technical_documents, "list_source_documents", lambda *_args, **_kwargs: [
        {"doc_type": "msds", "object_key": "64-17-5.html"},
    ])

    technical_documents.execute_fetch("run-1", "64-17-5", ["msds", "tds"])

    assert database.run.status == "FAILED"
    assert database.run.error_type == "未能拉取全部所选资料，缺少：TDS"
    assert database.run.result_json["missing_doc_types"] == ["tds"]
    assert database.run.result_json["files"][0]["doc_type"] == "msds"
    assert database.run.result_json["stages"][0]["status"] == "FAILED"


def test_source_object_key_accepts_only_safe_supported_files():
    assert technical_documents.source_object_key("64-17-5", "msds", "html") == (
        "chemicalops-msds",
        "64-17-5.html",
    )
    for values in (("../../etc/passwd", "msds", "html"), ("64-17-5", "property", "html")):
        with pytest.raises(ValueError):
            technical_documents.source_object_key(*values)


def test_missing_minio_source_is_reported_as_file_not_found(monkeypatch):
    class MissingObjectError(Exception):
        code = "NoSuchKey"

    class Client:
        def get_object(self, bucket, key):
            raise MissingObjectError()

    monkeypatch.setattr(technical_documents, "minio_client", lambda: Client())
    with pytest.raises(FileNotFoundError):
        technical_documents.get_source_file("64-17-5", "msds", "html")


def test_structured_preview_accepts_orm_section_objects():
    class Section:
        id = 1
        section_no = 1
        section_key = "identification"
        title = "Identification"
        content = "Chemical identity"
        char_count = len(content)

    preview = TechnicalDocumentPreviewRead.model_validate({
        "id": 1,
        "cas_no": "64-17-5",
        "doc_type": "msds",
        "title": "Ethanol",
        "name_zh": "乙醇",
        "source_bucket": "chemicalops-msds",
        "object_key": "64-17-5.html",
        "source_url": None,
        "parse_status": "PARSED",
        "reject_reason": None,
        "section_count": 1,
        "char_count": 18,
        "sha256": None,
        "updated_at": "2026-10-04T00:00:00",
        "meta_json": None,
        "sections": [Section()],
    })

    assert preview.sections[0].content == "Chemical identity"


def test_fetch_run_result_serializes_minio_datetimes():
    result = technical_documents.json_compatible_result({
        "files": [{"object_key": "64-17-5.html", "updated_at": datetime(2026, 10, 4, 12, 30)}],
    })

    assert json.loads(json.dumps(result))["files"][0]["updated_at"] == "2026-10-04T12:30:00"
