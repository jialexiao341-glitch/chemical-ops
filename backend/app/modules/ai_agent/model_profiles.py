"""AI 模型配置服务：维护模型目录、连通性探测并切换当前使用模型。"""

from time import monotonic
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai_agent import model_catalog
from app.modules.ai_agent.model import AIModelProfile
from app.modules.ai_agent.schema import (
    AIModelProfileCreate,
    AIModelProfileProbe,
    AIModelProfileRead,
    AIModelProfileUpdate,
)


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BusinessValidationError("API 地址必须是 http(s) 开头的完整地址")


def _masked_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    suffix = api_key[-4:] if len(api_key) >= 8 else "****"
    return f"••••{suffix}"


def to_read(row: AIModelProfile) -> AIModelProfileRead:
    return AIModelProfileRead(
        id=row.id,
        name=row.profile_name,
        model=row.model,
        base_url=row.base_url,
        api_key_masked=_masked_key(row.api_key),
        has_api_key=bool(row.api_key),
        context_window=row.context_window,
        max_tokens=row.max_tokens,
        reasoning_effort=row.reasoning_effort,
        temperature=float(row.temperature),
        timeout_seconds=row.timeout_seconds,
        max_retries=row.max_retries,
        max_concurrency=row.max_concurrency,
        is_default=row.is_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_profiles(db: Session, keyword: str | None = None) -> list[AIModelProfileRead]:
    statement = select(AIModelProfile).order_by(AIModelProfile.is_default.desc(), AIModelProfile.id)
    keyword = (keyword or "").strip()
    if keyword:
        statement = statement.where(
            AIModelProfile.profile_name.contains(keyword) | AIModelProfile.model.contains(keyword)
        )
    return [to_read(row) for row in db.scalars(statement).all()]


def get_profile(db: Session, profile_id: int) -> AIModelProfileRead:
    return to_read(_require_profile(db, profile_id))


def _require_profile(db: Session, profile_id: int) -> AIModelProfile:
    row = db.get(AIModelProfile, profile_id)
    if row is None:
        raise ResourceNotFoundError(f"模型配置 {profile_id} 不存在")
    return row


def _ensure_name_available(db: Session, name: str, exclude_id: int | None = None) -> None:
    statement = select(AIModelProfile.id).where(AIModelProfile.profile_name == name)
    if exclude_id is not None:
        statement = statement.where(AIModelProfile.id != exclude_id)
    if db.scalar(statement) is not None:
        raise DuplicateResourceError(f"模型名称 {name} 已存在")


def create_profile(db: Session, data: AIModelProfileCreate) -> AIModelProfileRead:
    _ensure_name_available(db, data.name)
    _validate_base_url(data.base_url)
    values = data.model_dump(exclude_none=True)
    row = AIModelProfile(
        profile_name=values.pop("name"),
        model=values.pop("model"),
        base_url=values.pop("base_url"),
        api_key=values.pop("api_key", None),
        context_window=values.pop("context_window", None),
        max_tokens=values.pop("max_tokens", None),
        **values,
    )
    row.is_default = db.scalar(select(AIModelProfile.id).limit(1)) is None
    db.add(row)
    db.commit()
    db.refresh(row)
    model_catalog.invalidate()
    return to_read(row)


def update_profile(db: Session, profile_id: int, data: AIModelProfileUpdate) -> AIModelProfileRead:
    row = _require_profile(db, profile_id)
    values = data.model_dump(exclude_unset=True)
    if "name" in values and values["name"]:
        _ensure_name_available(db, values["name"], exclude_id=profile_id)
        row.profile_name = values["name"]
    if "base_url" in values and values["base_url"]:
        _validate_base_url(values["base_url"])
        row.base_url = values["base_url"]
    if values.get("model"):
        row.model = values["model"]
    # 空字符串表示沿用已保存密钥；只有显式传入非空字符串才覆盖。
    if values.get("api_key"):
        row.api_key = values["api_key"]
    if "reasoning_effort" in values:
        row.reasoning_effort = values["reasoning_effort"]
    for field in ("context_window", "max_tokens", "temperature", "timeout_seconds", "max_retries", "max_concurrency"):
        if field in values and values[field] is not None:
            setattr(row, field, values[field])
    db.commit()
    db.refresh(row)
    model_catalog.invalidate()
    return to_read(row)


def delete_profile(db: Session, profile_id: int) -> None:
    row = _require_profile(db, profile_id)
    if row.is_default:
        raise BusinessValidationError("当前使用中的模型不能删除，请先切换到其他模型")
    db.delete(row)
    db.commit()
    model_catalog.invalidate()


def probe_profile(db: Session, profile_id: int) -> AIModelProfileProbe:
    """向目标模型发送一次最小请求，确认地址、密钥与模型标识可用。"""

    row = _require_profile(db, profile_id)
    _validate_base_url(row.base_url)
    api_key = (row.api_key or get_settings().openai_api_key or "").strip()
    if not api_key:
        raise BusinessValidationError("模型密钥未配置，请先填写 API 密钥")
    url = f"{row.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": row.model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    started = monotonic()
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=min(max(row.timeout_seconds, 1), 30),
        )
    except httpx.TimeoutException:
        return AIModelProfileProbe(ok=False, model=row.model, latency_ms=int((monotonic() - started) * 1000),
                                   message="连接超时，请检查 API 地址和网络")
    except httpx.RequestError:
        return AIModelProfileProbe(ok=False, model=row.model, latency_ms=int((monotonic() - started) * 1000),
                                   message="无法连接 API 地址，请检查地址、证书或网络")
    latency_ms = int((monotonic() - started) * 1000)
    if response.status_code != 200:
        return AIModelProfileProbe(ok=False, model=row.model, latency_ms=latency_ms,
                                   message=f"模型服务返回 HTTP {response.status_code}，请检查密钥、模型标识和额度")
    try:
        body = response.json()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError
    except (ValueError, AttributeError):
        return AIModelProfileProbe(ok=False, model=row.model, latency_ms=latency_ms,
                                   message="模型服务返回内容无法识别，请检查接口协议")
    return AIModelProfileProbe(ok=True, model=row.model, latency_ms=latency_ms, message="连通性正常")


def activate_profile(db: Session, profile_id: int) -> AIModelProfileRead:
    current_row = _require_profile(db, profile_id)
    if current_row.is_default:
        return to_read(current_row)
    probe = probe_profile(db, profile_id)
    if not probe.ok:
        raise BusinessValidationError(f"模型连通性检查失败：{probe.message}")
    row = db.scalar(select(AIModelProfile).where(AIModelProfile.id == profile_id).with_for_update())
    if row is None:
        raise ResourceNotFoundError(f"模型配置 {profile_id} 不存在")
    if row.is_default:
        return to_read(row)
    db.execute(update(AIModelProfile).values(is_default=False))
    row.is_default = True
    db.commit()
    db.refresh(row)
    model_catalog.invalidate()
    return to_read(row)