"""Qdrant 向量存储：知识库章节向量的建集合、写入与检索。

章节正文以 MySQL 为唯一内容源；Qdrant 只负责向量近邻与检索所需的
轻量 payload（含正文，检索时免二次回表）。
"""

from __future__ import annotations

from typing import Any

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


def search_sections(
    client: Any,
    vector: list[float],
    *,
    top_k: int = 8,
    cas_list: list[str] | None = None,
    name: str | None = None,
) -> list[dict]:
    """向量近邻检索；cas_list 非空时只在这些 CAS 的章节内搜索。"""

    from qdrant_client.models import FieldCondition, Filter, MatchAny

    target = collection_name(name)
    if not client.collection_exists(target):
        return []
    query_filter = None
    if cas_list:
        query_filter = Filter(
            must=[FieldCondition(key="cas_no", match=MatchAny(any=list(cas_list)))]
        )
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
