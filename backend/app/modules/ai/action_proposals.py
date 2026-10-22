"""提案版本、权限复核和领域执行的事务边界。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai import action_handlers
from app.modules.ai.model import AIAgentActionProposal
from app.modules.ai.schema import AIActionProposalConfirm, AIActionProposalPreview
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _authorize(db: Session, user: User, permission_code: str) -> None:
    if user.status != "ACTIVE":
        raise AuthorizationError("当前账号已停用")
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and permission_code not in permissions:
        raise AuthorizationError("当前账号没有执行该动作的权限")


def _preview(proposal: AIAgentActionProposal) -> AIActionProposalPreview:
    return AIActionProposalPreview(
        confirmation_id=proposal.confirmation_id,
        action_type=proposal.action_type,
        resource_type=proposal.resource_type,
        resource_id=proposal.resource_id,
        preview_version=proposal.preview_version,
        diff=proposal.diff or [],
        evidence=proposal.evidence or [],
        warnings=proposal.warnings or [],
        blockers=proposal.blockers or [],
        risk_level=proposal.risk_level,
        status=proposal.status,
        expires_at=proposal.expires_at.replace(tzinfo=timezone.utc),
        requires_user_confirmation=proposal.status == "PENDING",
    )


def propose_action(db: Session, user: User, action_type: str, payload: dict, *, idempotency_key: str) -> AIActionProposalPreview:
    handler = action_handlers.get_handler(action_type)
    _authorize(db, user, handler.permission_code)
    prepared = handler.prepare(db, user, payload)
    normalized = prepared["payload"]
    if prepared.get("blockers"):
        raise BusinessValidationError("动作提案存在阻塞项，不能生成可确认预览")
    existing = db.scalar(select(AIAgentActionProposal).where(
        AIAgentActionProposal.user_id == user.id,
        AIAgentActionProposal.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        if existing.action_type != action_type or existing.payload_hash != _hash(normalized):
            raise DuplicateResourceError("幂等键已用于其他动作或参数")
        return _preview(existing)
    proposal = AIAgentActionProposal(
        confirmation_id=uuid4().hex,
        user_id=user.id,
        action_type=action_type,
        resource_type=prepared.get("resource_type", handler.resource_type),
        resource_id=str(prepared["resource_id"]) if prepared.get("resource_id") is not None else None,
        preview_version=1,
        payload=normalized,
        payload_hash=_hash(normalized),
        expected_resource_snapshot=prepared.get("snapshot", {}),
        diff=prepared.get("diff", []),
        evidence=prepared.get("evidence", []),
        warnings=prepared.get("warnings", []),
        blockers=[],
        permission_code=handler.permission_code,
        risk_level=prepared.get("risk_level", "LOW"),
        idempotency_key=idempotency_key,
        expires_at=_now() + timedelta(minutes=10),
        status="PENDING",
    )
    db.add(proposal)
    db.commit()
    return _preview(proposal)


def _owned_proposal(db: Session, user: User, confirmation_id: str) -> AIAgentActionProposal:
    proposal = db.scalar(select(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == confirmation_id,
        AIAgentActionProposal.user_id == user.id,
    ).with_for_update())
    if proposal is None:
        raise ResourceNotFoundError("动作提案不存在或不属于当前用户")
    return proposal


def revise_action(db: Session, user: User, confirmation_id: str, preview_version: int, payload: dict) -> AIActionProposalPreview:
    proposal = _owned_proposal(db, user, confirmation_id)
    handler = action_handlers.get_handler(proposal.action_type)
    _authorize(db, user, proposal.permission_code)
    if proposal.status != "PENDING" or proposal.expires_at <= _now():
        raise DuplicateResourceError("动作提案已失效，请重新生成")
    if proposal.preview_version != preview_version:
        raise DuplicateResourceError("动作提案版本已变化，请刷新后重试")
    prepared = handler.prepare(db, user, payload)
    if prepared.get("blockers"):
        raise BusinessValidationError("动作提案存在阻塞项，不能保存为可确认预览")
    proposal.payload = prepared["payload"]
    proposal.payload_hash = _hash(proposal.payload)
    proposal.expected_resource_snapshot = prepared.get("snapshot", {})
    proposal.diff = prepared.get("diff", [])
    proposal.evidence = prepared.get("evidence", [])
    proposal.warnings = prepared.get("warnings", [])
    proposal.resource_id = str(prepared["resource_id"]) if prepared.get("resource_id") is not None else None
    proposal.preview_version += 1
    db.commit()
    return _preview(proposal)


def cancel_action(db: Session, user: User, confirmation_id: str, preview_version: int) -> None:
    proposal = _owned_proposal(db, user, confirmation_id)
    _authorize(db, user, proposal.permission_code)
    if proposal.status != "PENDING" or proposal.expires_at <= _now():
        raise DuplicateResourceError("动作提案已失效")
    if proposal.preview_version != preview_version:
        raise DuplicateResourceError("动作提案版本已变化")
    proposal.status = "CANCELLED"
    db.commit()


def confirm_action(db: Session, user: User, data: AIActionProposalConfirm) -> dict:
    proposal = _owned_proposal(db, user, data.confirmation_id)
    handler = action_handlers.get_handler(proposal.action_type)
    _authorize(db, user, proposal.permission_code)
    if proposal.status == "EXECUTED":
        return proposal.result or {}
    if proposal.preview_version != data.preview_version:
        raise DuplicateResourceError("动作提案版本已变化，请重新核对")
    if proposal.status != "PENDING":
        raise DuplicateResourceError("动作提案已失效，请重新生成")
    if proposal.expires_at <= _now():
        proposal.status = "EXPIRED"
        db.commit()
        raise DuplicateResourceError("动作提案已过期，请重新生成")
    if _hash(proposal.payload) != proposal.payload_hash:
        raise BusinessValidationError("动作提案参数校验失败，请重新生成")
    handler.validate_current(db, user, proposal)
    result = handler.execute(db, user, proposal, commit=False)
    proposal.status = "EXECUTED"
    proposal.result = result
    proposal.executed_at = _now()
    db.commit()
    return result
