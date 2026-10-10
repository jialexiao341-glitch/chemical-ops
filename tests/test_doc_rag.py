"""文档 RAG 测试：意图识别、CAS 提取、混合检索、上下文构建与 chat 注入。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import intent as intent_module
from app.modules.ai import service as ai_service
from app.modules.ai.intent import Intent, classify_intent, extract_valid_cas, valid_cas_checksum
from app.modules.ai.schema import AIChatMessage, AIChatResponse
from app.modules.doc_kb import retrieve as retrieve_module
from app.modules.doc_kb import vector_store
from app.modules.doc_kb.embedding import embed_texts
from app.modules.doc_kb.retrieve import (
    DocSectionHit,
    build_doc_context,
    requested_single_doc_type,
    requested_msds_section,
    resolve_doc_targets,
    retrieve_sections,
)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("乙醇的 TDS 分子量是多少？", "tds"),
        ("乙醇的物性页熔点是多少？", "property"),
        ("乙醇的 MSDS 第9节闪点是多少？", "msds"),
        ("比较乙醇的 MSDS 和 TDS", None),
        ("乙醇的安全资料中闪点是多少？", "msds"),
        ("乙醇产品资料中的分子式", "tds"),
        ("结合乙醇安全资料与产品技术资料", None),
    ],
)
def test_requested_single_doc_type(question, expected):
    assert requested_single_doc_type(question) == expected


# ---------- 意图与 CAS ----------


def test_doc_intent_triggered_by_property_keywords():
    assert classify_intent("乙醇的闪点是多少").intent is Intent.DOC
    assert classify_intent("这个物质的 MSDS 在哪").intent is Intent.DOC
    assert classify_intent("64-17-5 的危险性信号词").intent is Intent.DOC


def test_cas_pattern_intent_with_checksum():
    result = classify_intent("查一下 CAS 64-17-5 的文档")
    assert result.intent is Intent.DOC
    assert result.reason == "cas_pattern"


def test_date_like_string_is_not_cas():
    assert extract_valid_cas("2026-09-22 的采购订单") == []
    assert classify_intent("2026-09-22 的采购订单").intent is Intent.QUERY


def test_cas_checksum_validation():
    assert valid_cas_checksum("64-17-5")
    assert extract_valid_cas("文档见 64-17-5 与 67-56-1") == ["64-17-5", "67-56-1"]
    # 校验码不合法的随机串不算 CAS
    assert extract_valid_cas("12-34-5") == []


def test_existing_intents_still_work():
    assert classify_intent("查询本月采购订单金额").intent is Intent.QUERY
    assert classify_intent("明天天气怎么样").intent is Intent.UNSUPPORTED
    assert classify_intent("你有什么功能").intent is Intent.PROJECT
    assert classify_intent("你好").intent is Intent.GREETING
    # 无标记的普通问法仍走引导兜底（注意「最近」「按」等词本身是 QUERY 标记，不能用作本例）
    assert classify_intent("周末有什么安排吗").intent is Intent.UNSUPPORTED
    assert classify_intent("周末有什么安排吗").reason == "no_supported_marker"


# ---------- 目标解析（真实开发库数据） ----------


def test_resolve_doc_targets_by_chinese_name(db_session):
    targets = asyncio.run(resolve_doc_targets(db_session, "乙醇的沸点是多少"))
    assert "64-17-5" in targets


def test_resolve_doc_targets_by_english_name(db_session):
    targets = asyncio.run(resolve_doc_targets(db_session, "flash point of Ethanol"))
    assert "64-17-5" in targets


def test_resolve_doc_targets_empty_for_unrelated(db_session):
    targets = asyncio.run(resolve_doc_targets(db_session, "今天天气如何"))
    assert targets == []


# ---------- 向量层（假客户端，不连 Qdrant） ----------


class FakeQdrantClient:
    def __init__(self, *, exists=False, dim=4, points=None):
        self._exists = exists
        self._dim = dim
        self.created = None
        self.deleted = []
        self.upserted = []
        self.last_query = None
        self._points = points or []

    def collection_exists(self, _name):
        return self._exists

    def create_collection(self, name, vectors_config):
        self._exists = True
        self.created = (name, vectors_config)
        return True

    def delete_collection(self, name):
        self.deleted.append(name)
        self._exists = False
        return True

    def get_collection(self, _name):
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self._dim)))
        )

    def upsert(self, name, points, wait=False):
        self.upserted.append((name, points, wait))
        return True

    def query_points(self, name, query, query_filter=None, limit=8, with_payload=True):
        self.last_query = {"name": name, "filter": query_filter, "limit": limit}
        return SimpleNamespace(points=self._points[:limit])


def test_ensure_collection_creates_with_dim():
    client = FakeQdrantClient(exists=False)

    vector_store.ensure_collection(client, 1024, name="t1")

    assert client.created is not None
    name, config = client.created
    assert name == "t1"
    assert config.size == 1024


def test_ensure_collection_rejects_dim_mismatch():
    client = FakeQdrantClient(exists=True, dim=768)

    with pytest.raises(BusinessValidationError, match="维度"):
        vector_store.ensure_collection(client, 1024, name="t2")


def test_ensure_collection_recreate():
    client = FakeQdrantClient(exists=True, dim=768)

    vector_store.ensure_collection(client, 1024, name="t3", recreate=True)

    assert client.deleted == ["t3"]
    assert client.created is not None


def test_upsert_and_search_roundtrip():
    client = FakeQdrantClient(
        exists=True,
        points=[
            SimpleNamespace(id=11, score=0.92, payload={"cas_no": "64-17-5", "content": "Flash point 13"}),
            SimpleNamespace(id=12, score=0.70, payload={"cas_no": "67-56-1", "content": "Boiling"}),
        ],
    )

    written = vector_store.upsert_sections(
        client,
        [{"id": 11, "vector": [0.1] * 4, "payload": {"cas_no": "64-17-5", "content": "x"}}],
        name="t4",
    )
    assert written == 1
    assert client.upserted[0][0] == "t4"
    assert client.upserted[0][1][0].id == 11

    hits = vector_store.search_sections(client, [0.1] * 4, top_k=5, cas_list=["64-17-5"], name="t4")
    assert [hit["id"] for hit in hits] == [11, 12]
    # 过滤条件按 cas_no 传给 Qdrant
    condition = client.last_query["filter"].must[0]
    assert condition.key == "cas_no"


def test_search_returns_empty_when_collection_missing():
    client = FakeQdrantClient(exists=False)
    assert vector_store.search_sections(client, [0.1], name="t5") == []


# ---------- embedding（假 httpx，不连 LM Studio） ----------


def test_embed_texts_orders_by_index(monkeypatch: pytest.MonkeyPatch):
    from app.modules.doc_kb import embedding

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(embedding.httpx, "AsyncClient", FakeAsyncClient)

    vectors = asyncio.run(embed_texts(["a", "b"]))

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_embed_texts_rejects_count_mismatch(monkeypatch: pytest.MonkeyPatch):
    from app.modules.doc_kb import embedding

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [1.0]}]}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(embedding.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(BusinessValidationError, match="数量"):
        asyncio.run(embed_texts(["a", "b"]))


# ---------- 混合检索 ----------


def test_explicit_msds_section_routes_to_database(monkeypatch: pytest.MonkeyPatch, db_session):
    async def should_not_embed(_texts, _settings=None):
        raise AssertionError("明确的 MSDS 章节应直接读取已解析文档")

    monkeypatch.setattr(retrieve_module, "embed_texts", should_not_embed)
    assert requested_msds_section("乙醇MSDS第9节的闪点是多少？") == 9
    assert requested_msds_section("乙醇 MSDS 与 TDS 有什么区别？") is None
    assert requested_msds_section("乙醇 MSDS 第9节和第10节有什么区别？") is None

    hits = asyncio.run(retrieve_sections(db_session, "乙醇（CAS 64-17-5）的MSDS第9节闪点是多少？"))

    assert hits
    assert hits[0].cas_no == "64-17-5"
    assert hits[0].doc_type == "msds"
    assert hits[0].section_no == 9
    assert hits[0].source == "exact"
    assert "Flash point" in hits[0].content


def _hit_payload(section_id, cas="64-17-5", content="Flash point13C"):
    return {
        "id": section_id,
        "score": 0.9,
        "payload": {
            "cas_no": cas,
            "doc_type": "msds",
            "section_no": 9,
            "section_key": "SECTION 9",
            "title": "SECTION 9",
            "name_zh": "乙醇",
            "content": content,
        },
    }


def test_retrieve_merges_vector_and_bridge(monkeypatch: pytest.MonkeyPatch, db_session):
    async def fake_embed(_texts, _settings=None):
        return [[0.1, 0.2]]

    class FakeClient:
        pass

    monkeypatch.setattr(retrieve_module, "embed_texts", fake_embed)
    monkeypatch.setattr(vector_store, "get_client", lambda: FakeClient())
    monkeypatch.setattr(
        vector_store,
        "search_sections",
        lambda *_args, **_kwargs: [{"id": 1, "score": 0.95, "payload": {"cas_no": "64-17-5", "content": "vector content"}}],
    )

    hits = asyncio.run(retrieve_sections(db_session, "乙醇的闪点", top_k=10))

    assert hits, "桥接或向量至少一路应有结果"
    assert any(hit.source == "vector" for hit in hits)
    # 桥接章节（真实库中乙醇已 PARSED）应并入且带中文名
    bridge = [hit for hit in hits if hit.source == "bridge"]
    if bridge:  # 开发库有数据时必然非空
        assert bridge[0].cas_no == "64-17-5"
    # id=1 的向量命中不应重复
    assert len({hit.id for hit in hits}) == len(hits)


def test_retrieve_falls_back_to_bridge_when_embed_fails(monkeypatch: pytest.MonkeyPatch, db_session):
    async def broken_embed(_texts, _settings=None):
        raise BusinessValidationError("Embedding 服务不可用")

    monkeypatch.setattr(retrieve_module, "embed_texts", broken_embed)

    hits = asyncio.run(retrieve_sections(db_session, "乙醇的闪点是多少"))

    assert hits, "embedding 故障时桥接必须兜底"
    assert all(hit.source == "bridge" for hit in hits)
    assert hits[0].cas_no == "64-17-5"
    assert hits[0].name_zh == "乙醇"


def test_retrieve_vector_only_when_no_target(db_session, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed(_texts, _settings=None):
        return [[0.5]]

    monkeypatch.setattr(retrieve_module, "embed_texts", fake_embed)
    monkeypatch.setattr(vector_store, "get_client", lambda: object())
    monkeypatch.setattr(
        retrieve_module.vector_store,
        "search_sections",
        lambda *_args, **_kwargs: [_hit_payload(99, cas="75-05-8", content="Acetonitrile properties")],
    )

    hits = asyncio.run(retrieve_sections(db_session, "flash point of some unknown solvent"))

    assert len(hits) == 1
    assert hits[0].source == "vector"
    assert hits[0].cas_no == "75-05-8"


def test_property_boilerplate_does_not_displace_structured_fields(db_session, monkeypatch):
    async def fake_embed(_texts, _settings=None):
        return [[0.5]]

    monkeypatch.setattr(retrieve_module, "embed_texts", fake_embed)
    monkeypatch.setattr(vector_store, "get_client", lambda: object())
    crowded = [
        {"id": -index, "score": 0.99, "payload": {
            "cas_no": "64-17-5", "doc_type": "property",
            "content": "Ethanol supplier catalog and navigation links",
        }} for index in range(1, 19)
    ]
    monkeypatch.setattr(vector_store, "search_sections", lambda *_args, **_kwargs: crowded)
    hits = asyncio.run(retrieve_sections(db_session, "乙醇的闪点和初沸点分别是多少？"))
    assert hits[0].doc_type == "msds"
    assert hits[0].section_no == 9
    assert hits[0].source == "bridge"
    assert "Flash point" in hits[0].content
    assert len(hits) <= 6
    assert all(hit.cas_no == "64-17-5" for hit in hits)


def test_cross_source_fields_survive_embedding_outage(db_session, monkeypatch):
    async def broken_embed(_texts, _settings=None):
        raise BusinessValidationError("Embedding unavailable")

    monkeypatch.setattr(retrieve_module, "embed_texts", broken_embed)
    hits = asyncio.run(retrieve_sections(
        db_session, "结合乙醇安全资料和产品技术资料，闪点与分子量分别是多少？", top_k=2,
    ))
    assert {hit.doc_type for hit in hits} == {"msds", "tds"}
    assert next(hit for hit in hits if hit.doc_type == "msds").section_no == 9
    assert all(hit.source == "bridge" and hit.cas_no == "64-17-5" for hit in hits)


def test_natural_single_source_stays_scoped(db_session, monkeypatch):
    async def should_not_embed(_texts, _settings=None):
        pytest.fail("Single explicit source should be read directly")

    monkeypatch.setattr(retrieve_module, "embed_texts", should_not_embed)
    hits = asyncio.run(retrieve_sections(db_session, "乙醇产品资料里的分子式是什么？"))
    assert hits and all(hit.doc_type == "tds" and hit.source == "exact" for hit in hits)


def test_field_ranking_ignores_labels_outside_context():
    prefix = "Supplier links " * 120
    assert retrieve_module._field_relevance("闪点", "property", None, prefix + "Flash point 13") == 0


# ---------- 上下文构建 ----------


def test_build_doc_context_contains_source_and_citations():
    hits = [
        DocSectionHit(
            id=1,
            cas_no="64-17-5",
            doc_type="msds",
            section_no=9,
            section_key="SECTION 9",
            title="SECTION 9: Physical",
            name_zh="乙醇",
            content="Flash point13 °C",
            score=0.9,
            source="vector",
        )
    ]

    context, citations = build_doc_context(hits)

    assert "乙醇" in context
    assert "64-17-5" in context
    assert "Flash point13" in context
    assert "禁止编造" in context
    assert citations[0]["type"] == "doc_kb"
    assert citations[0]["cas_no"] == "64-17-5"
    assert citations[0]["section_no"] == 9


def test_build_doc_context_respects_char_budget():
    big = DocSectionHit(
        id=1,
        cas_no="64-17-5",
        doc_type="msds",
        section_no=None,
        section_key="intro",
        title=None,
        name_zh="乙醇",
        content="x" * 500,
        score=0.9,
        source="vector",
    )
    second = DocSectionHit(
        id=2,
        cas_no="64-17-5",
        doc_type="msds",
        section_no=None,
        section_key="intro2",
        title=None,
        name_zh="乙醇",
        content="y" * 500,
        score=0.8,
        source="vector",
    )

    _context, citations = build_doc_context([big, second], max_chars=600)

    # 第一块无论如何保留，第二块超预算被截断
    assert len(citations) == 1


# ---------- chat 注入（接口级） ----------


def _fake_chat_response(content: str) -> AIChatResponse:
    return AIChatResponse(
        message=AIChatMessage(role="assistant", content=content),
        conversation_id=0,
        model="deepseek-flash",
        provider="openai_compatible",
        answer=content,
    )


def _fake_hits():
    return [
        DocSectionHit(
            id=1,
            cas_no="64-17-5",
            doc_type="msds",
            section_no=9,
            section_key="SECTION 9",
            title="SECTION 9",
            name_zh="乙醇",
            content="Flash point13 °C - closed cup",
            score=0.95,
            source="bridge",
        )
    ]


def test_chat_doc_path_injects_context_and_citations(client, demo_password, monkeypatch):
    from app.modules.ai import routing
    async def understand(*args, **kwargs):
        return routing.Understanding(purpose='query', tasks=['document'])
    monkeypatch.setattr(routing, 'understand', understand)
    captured = {}

    async def fake_chat(data, settings=None, **kwargs):
        captured["context"] = (kwargs.get("attachment_context") or [""])[0]
        return _fake_chat_response("乙醇的闪点是 13 °C（闭杯）。（来源：乙醇 MSDS SECTION 9）")

    async def fake_retrieve(_db, _question, **_kwargs):
        return _fake_hits()

    monkeypatch.setattr(retrieve_module, "retrieve_sections", fake_retrieve)
    monkeypatch.setattr(ai_service, "chat", fake_chat)

    response = client.post(
        "/api/v1/ai/chat",
        headers={"Authorization": f"Bearer {client.post('/api/v1/auth/login', json={'username': 'system_admin', 'password': demo_password}).json()['access_token']}"},
        json={"messages": [{"role": "user", "content": "乙醇的闪点是多少"}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "13" in body["answer"]
    assert body["citations"][0]["type"] == "doc_kb"
    assert body["citations"][0]["cas_no"] == "64-17-5"
    # 注入的上下文包含真实章节内容
    assert "Flash point" in captured["context"]
    # 历史消息持久化了 citations
    history = client.get(
        f"/api/v1/ai/conversations/{body['conversation_id']}/messages",
        headers={"Authorization": f"Bearer {client.post('/api/v1/auth/login', json={'username': 'system_admin', 'password': demo_password}).json()['access_token']}"},
    )
    assert history.json()["items"][-1]["citations"][0]["type"] == "doc_kb"


def test_chat_doc_path_empty_hits_gives_guidance(client, demo_password, monkeypatch):
    from app.modules.ai import routing
    async def understand(*args, **kwargs):
        return routing.Understanding(purpose='query', tasks=['document'])
    monkeypatch.setattr(routing, 'understand', understand)
    async def fake_retrieve(_db, _question, **_kwargs):
        return []

    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("检索为空时不应调用 LLM")

    monkeypatch.setattr(retrieve_module, "retrieve_sections", fake_retrieve)
    monkeypatch.setattr(ai_service, "chat", fake_chat)

    token = client.post(
        "/api/v1/auth/login", json={"username": "system_admin", "password": demo_password}
    ).json()["access_token"]
    response = client.post(
        "/api/v1/ai/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "XYZ-99 的闪点"}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "没有检索到可用的化学品文档摘录" in body["answer"]
    assert body["model"] == "rule-based"
    assert body["citations"] is None


def test_stream_doc_path_emits_deltas_and_citations(client, demo_password, monkeypatch):
    from app.modules.ai import routing
    async def understand(*args, **kwargs):
        return routing.Understanding(purpose='query', tasks=['document'])
    monkeypatch.setattr(routing, 'understand', understand)
    async def fake_retrieve(_db, _question, **_kwargs):
        return _fake_hits()

    async def fake_chat(*_args, **_kwargs):
        return _fake_chat_response("闪点13°C。")

    monkeypatch.setattr(retrieve_module, "retrieve_sections", fake_retrieve)
    monkeypatch.setattr(ai_service, "chat", fake_chat)

    token = client.post(
        "/api/v1/auth/login", json={"username": "system_admin", "password": demo_password}
    ).json()["access_token"]
    response = client.post(
        "/api/v1/ai/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"messages": [{"role": "user", "content": "乙醇闪点"}]},
    )

    assert response.status_code == 200, response.text
    text = response.text
    assert "event: delta" in text
    assert "event: done" in text
    done_line = next(line for line in text.splitlines() if line.startswith("data:") and "event" not in line and "conversation_id" in line)
    # done 事件的 data 行带 citations
    data_lines = [line for line in text.splitlines() if line.startswith("data:")]
    done_data = None
    for line in data_lines:
        try:
            payload = json.loads(line[len("data:"):])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "citations" in payload:
            done_data = payload
    assert done_data is not None
    assert done_data["citations"][0]["type"] == "doc_kb"
    assert "闪点" in done_data["answer"]
