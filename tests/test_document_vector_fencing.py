"""Actual Qdrant conditional writes, using a fresh disposable collection."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from app.core.errors import BusinessValidationError
from app.modules.doc_kb import vector_store as store


@pytest.fixture
def vectors():
    client = QdrantClient(host="127.0.0.1", port=6333)
    name = "chemicalops_acceptance_" + uuid4().hex
    store.require_conditional_writes(client)
    store.ensure_collection(client, 2, name=name)
    yield client, name
    client.delete_collection(name)
    client.close()


def row(point_id, content, cas="64-17-5"):
    return {"id": point_id, "vector": [1.0, 0.0],
            "payload": {"cas_no": cas, "doc_type": "msds", "content": content}}


def write(client, name, rows, generation, cas="64-17-5"):
    store.prepare_document_points(client, rows, cas=cas, doc_type="msds", generation=generation, name=name)
    store.conditional_upsert_sections(client, rows, cas=cas, doc_type="msds", generation=generation, name=name)


def test_obsolete_update_cannot_overwrite_or_resurrect_deleted_section(vectors):
    client, name = vectors
    write(client, name, [row(1, "old"), row(2, "removed")], 1)
    store.upsert_sections(client, [row(99, "legacy orphan without generation")], name=name)
    write(client, name, [row(3, "other", cas="67-56-1")], 1, cas="67-56-1")
    write(client, name, [row(1, "new")], 2)
    store.cleanup_document_points(client, [1], cas="64-17-5", doc_type="msds", generation=2, name=name)
    # Requests already sent by an obsolete worker arrive after the newer completion.
    store.conditional_upsert_sections(client, [row(1, "late"), row(2, "late")],
        cas="64-17-5", doc_type="msds", generation=1, name=name)
    points = client.retrieve(name, [1, 2, 3, 99])
    assert {point.id for point in points} == {1, 3}
    assert points[0].payload["content"] == "new"
    assert next(point for point in points if point.id == 3).payload["content"] == "other"


def test_batches_stay_searchable_and_late_seeds_stay_inert(vectors):
    client, name = vectors
    write(client, name, [row(1, "first")], 2)
    write(client, name, [row(2, "second")], 2)
    # An obsolete insert-only seed can never replace current content.
    store.prepare_document_points(client, [row(1, "late"), row(9, "late new seed")],
        cas="64-17-5", doc_type="msds", generation=1, name=name)
    hits = store.search_sections(client, [1.0, 0.0], name=name)
    assert {point["id"] for point in hits} == {1, 2}
    assert next(point for point in hits if point["id"] == 1)["payload"]["content"] == "first"


def test_server_version_gate():
    with pytest.raises(BusinessValidationError, match="1.16"):
        store.require_conditional_writes(SimpleNamespace(info=lambda: SimpleNamespace(version="1.15.9")))
