"""Qdrant 向量存储：知识库章节向量的建集合、写入与检索。

章节正文以 MySQL 为唯一内容源；Qdrant 只负责向量近邻与检索所需的
轻量 payload（含正文，检索时免二次回表）。
"""

from __future__ import annotations

from typing import Any
import inspect
import re

from app.core.config import get_settings
from app.core.errors import BusinessValidationError


def collection_name(name: str | None = None) -> str:
    return name or get_settings().qdrant_collection


def get_client() -> Any:
    """创建 Qdrant 客户端（不在构造时连接，调用失败会在实际请求时抛出）。"""

    settings = get_settings()
    from qdrant_client import QdrantClient

    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection(client: Any, dim: int, *, name: str | None = None, recreate: bool = False) -> str:
    """确保集合存在且维度一致；--recreate 场景先删除重建。"""

    from qdrant_client.models import Distance, VectorParams

    target = collection_name(name)
    if recreate and client.collection_exists(target):
        client.delete_collection(target)
    if not client.collection_exists(target):
        client.create_collection(target, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        return target
    info = client.get_collection(target)
    vectors = info.config.params.vectors
    existing_dim = getattr(vectors, "size", None)
    if existing_dim is not None and int(existing_dim) != dim:
        raise BusinessValidationError(
            f"Qdrant 集合 {target} 维度为 {existing_dim}，与当前向量维度 {dim} 不一致；换模型后请用 --recreate 重建"
        )
    return target


def upsert_sections(client: Any, rows: list[dict], *, name: str | None = None) -> int:
    """批量写入章节向量；row = {"id": int, "vector": list[float], "payload": dict}。"""

    if not rows:
        return 0
    from qdrant_client.models import PointStruct

    points = [PointStruct(id=row["id"], vector=row["vector"], payload=row["payload"]) for row in rows]
    client.upsert(collection_name(name), points=points, wait=True)
    return len(points)


def require_conditional_writes(client: Any):
    """Fail before touching points if either server or SDK lacks conditional writes."""
    version = client.info().version
    match = re.match(r"(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (1, 16):
        raise BusinessValidationError("受保护向量写入要求 Qdrant >= 1.16")
    if not {"update_filter", "update_mode"}.issubset(inspect.signature(client.upsert).parameters):
        raise BusinessValidationError("请升级 qdrant-client 以支持条件写入")


def document_filter(cas: str, doc_type: str, generation: int):
    from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, MatchValue, PayloadField, Range
    return Filter(must=[FieldCondition(key="cas_no", match=MatchValue(value=cas)),
        FieldCondition(key="doc_type", match=MatchValue(value=doc_type)),
        Filter(should=[FieldCondition(key="vector_generation", range=Range(lte=generation)),
            IsEmptyCondition(is_empty=PayloadField(key="vector_generation"))])])


def prepare_document_points(client, rows, *, cas, doc_type, generation, name=None):
    """Create inert points without overwriting, then fence all older document points."""
    from qdrant_client.models import PointStruct, UpdateMode, WriteOrdering
    target = collection_name(name)
    seeds = [PointStruct(id=row["id"], vector=[0.0] * len(row["vector"]),
        payload={"cas_no": cas, "doc_type": doc_type, "vector_generation": 0, "index_pending": True}) for row in rows]
    if seeds:
        client.upsert(target, points=seeds, wait=True, ordering=WriteOrdering.STRONG, update_mode=UpdateMode.INSERT_ONLY)
    selector = document_filter(cas, doc_type, generation)
    selector.must[2].should[0].range.lte = None
    selector.must[2].should[0].range.lt = generation
    client.set_payload(target, {"vector_generation": generation, "index_pending": True},
        points=selector, wait=True, ordering=WriteOrdering.STRONG)


def conditional_upsert_sections(client, rows, *, cas, doc_type, generation, name=None):
    from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct, UpdateMode, WriteOrdering
    points = [PointStruct(id=row["id"], vector=row["vector"],
        payload={**row["payload"], "vector_generation": generation, "index_pending": False}) for row in rows]
    if points:
        client.upsert(collection_name(name), points=points, wait=True, ordering=WriteOrdering.STRONG,
            update_mode=UpdateMode.UPDATE_ONLY,
            update_filter=Filter(must=[FieldCondition(key="vector_generation", match=MatchValue(value=generation)),
                FieldCondition(key="cas_no", match=MatchValue(value=cas)),
                FieldCondition(key="doc_type", match=MatchValue(value=doc_type))]))
    return len(points)


def cleanup_document_points(client, valid_ids, *, cas, doc_type, generation, name=None):
    from qdrant_client.models import HasIdCondition, WriteOrdering
    selector = document_filter(cas, doc_type, generation)
    if valid_ids:
        selector.must_not = [HasIdCondition(has_id=list(valid_ids))]
    client.delete(collection_name(name), points_selector=selector, wait=True, ordering=WriteOrdering.STRONG)


def search_sections(
    client: Any,
    vector: list[float],
    *,
    top_k: int = 8,
    cas_list: list[str] | None = None,
    name: str | None = None,
) -> list[dict]:
    """向量近邻检索；cas_list 非空时只在这些 CAS 的章节内搜索。"""

    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    target = collection_name(name)
    if not client.collection_exists(target):
        return []
    query_filter = Filter(must_not=[FieldCondition(key="index_pending", match=MatchValue(value=True))])
    if cas_list:
        query_filter.must = [FieldCondition(key="cas_no", match=MatchAny(any=list(cas_list)))]
    response = client.query_points(
        target,
        query=vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )
    results: list[dict] = []
    for point in response.points:
        payload = point.payload or {}
        results.append({"id": point.id, "score": float(point.score), "payload": payload})
    return results
