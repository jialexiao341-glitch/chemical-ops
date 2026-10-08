"""Real isolated SQL + Qdrant; embedding is a deterministic test substitute."""

import asyncio
from argparse import Namespace
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.modules.doc_kb import service, vector_store
from app.modules.doc_kb.model import AiDocumentSection
from scripts import embed_sections
from tests.test_task_queue_delivery import queue_engine, db


def test_interrupted_embedding_rebuilds_only_target_document(db, monkeypatch):
    parsed = service.ParsedDoc(cas="64-17-5", doc_type="tds", sections=[
        service.ParsedSection(1, "page-1", "First", "first source"),
        service.ParsedSection(2, "page-2", "Second", "second source")])
    service.store_parsed(db, cas=parsed.cas, doc_type="tds", bucket="test", object_key="test.pdf",
                         parsed=parsed, sha256="a" * 64)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    client = QdrantClient(host="127.0.0.1", port=6333)
    name = "chemicalops_acceptance_" + uuid4().hex
    settings = Settings(_env_file=None, qdrant_collection=name)
    monkeypatch.setattr(embed_sections, "SessionLocal", factory)
    monkeypatch.setattr(embed_sections, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store, "get_settings", lambda: settings)
    monkeypatch.setattr(vector_store, "get_client", lambda: client)
    batches = []
    async def embedding(texts, _settings):
        batches.append(texts)
        if len(batches) == 2:
            raise ConnectionError("simulated interruption")
        return [[1.0, 0.0] for _text in texts]
    monkeypatch.setattr(embed_sections, "embed_texts", embedding)
    args = Namespace(cas=[parsed.cas], doc_type="tds", recreate=False, batch=1)
    try:
        with pytest.raises(ConnectionError):
            asyncio.run(embed_sections.run(args))
        monkeypatch.setattr(embed_sections, "embed_texts", lambda texts, settings: successful_embedding(texts))
        asyncio.run(embed_sections.run(args))
        assert len(vector_store.search_sections(client, [1.0, 0.0], name=name)) == 2
        assert client.count(name, exact=True).count == 2
        # Source shrinks: stable page 1 survives, vanished page 2 and its point disappear.
        parsed.sections = [service.ParsedSection(1, "page-1", "First", "changed source")]
        service.store_parsed(db, cas=parsed.cas, doc_type="tds", bucket="test", object_key="test.pdf",
                             parsed=parsed, sha256="b" * 64)
        asyncio.run(embed_sections.run(args))
        hits = vector_store.search_sections(client, [1.0, 0.0], name=name)
        assert len(hits) == 1 and hits[0]["payload"]["content"] == "changed source"
        assert client.count(name, exact=True).count == 1
    finally:
        if client.collection_exists(name):
            client.delete_collection(name)
        client.close()


async def successful_embedding(texts):
    return [[1.0, 0.0] for _text in texts]
