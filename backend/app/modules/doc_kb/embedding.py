"""文档知识库向量化：OpenAI 兼容 embeddings 接口（默认本地 LM Studio）。"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import BusinessValidationError

EMBEDDING_TIMEOUT_SECONDS = 120


async def embed_texts(texts: list[str], settings: Settings | None = None) -> list[list[float]]:
    """批量文本向量化；返回与输入等长、同维度的向量列表。"""

    if not texts:
        return []
    runtime = settings or get_settings()
    url = f"{runtime.embedding_base_url.rstrip('/')}/embeddings"
    payload = {"model": runtime.embedding_model, "input": texts}
    headers = {
        "Authorization": f"Bearer {runtime.embedding_api_key or 'none'}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise BusinessValidationError(f"Embedding 服务不可用（{runtime.embedding_base_url}）：{exc}") from exc
    except ValueError as exc:
        raise BusinessValidationError("Embedding 服务返回了无法识别的结果") from exc

    items = body.get("data")
    if not isinstance(items, list) or len(items) != len(texts):
        raise BusinessValidationError("Embedding 服务返回的向量数量与输入不一致")
    ordered = sorted(items, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in ordered]
    if any(not isinstance(vector, list) or not vector for vector in vectors):
        raise BusinessValidationError("Embedding 服务返回了空向量")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise BusinessValidationError("Embedding 服务返回的向量维度不一致")
    return vectors
