"""提案版本、权限复核和领域执行的事务边界。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai import action_handlers
from app.modules.ai.model import AIAgentActionProposal
from app.modules.ai.schema import (AIActionProposalConfirm, AIActionProposalPage, AIActionProposalPreview,
                                   AIActionProposalRead)
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


INBOX_ACTION_TYPES = ("purchase_request.update_draft", "purchase_request.submit", "rfq.create_draft")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _required_permission_codes(action_type: str, permission_code: str) -> set[str]:
    required = {permission_code}
    if action_type == "rfq.create_draft":
        required.add("master.suppliers.read")
    return required


def _authorize(db: Session, user: User, permission_code: str, *, action_type: str | None = None) -> None:
    if user.status != "ACTIVE":
        raise AuthorizationError("当前账号已停用")
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    required = _required_permission_codes(action_type, permission_code) if action_type else {permission_code}
    if "SYS_ADMIN" not in roles and not required <= permissions:
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
    _authorize(db, user, handler.permission_code, action_type=action_type)
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


def _owned_proposal(db: Session, user: User, confirmation_id: str, *, for_update: bool = True) -> AIAgentActionProposal:
    query = select(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == confirmation_id,
        AIAgentActionProposal.user_id == user.id,
    )
    proposal = db.scalar(query.with_for_update() if for_update else query)
    if proposal is None:
        raise ResourceNotFoundError("动作提案不存在或不属于当前用户")
    return proposal


def _proposal_read(db: Session, user: User, proposal: AIAgentActionProposal) -> tuple[AIActionProposalRead, bool]:
    """Build a safe inbox view and persist only deterministic expiry/invalidation transitions."""
    changed = False
    availability = "AVAILABLE"
    reason = {
        "EXPIRED": "提案已过期，请重新生成",
        "INVALIDATED": "关联资源或状态已变化，请重新生成提案",
    }.get(proposal.status)
    permission_codes = set(get_user_permission_codes(db, user.id))
    roles = set(get_user_role_codes(db, user.id))
    required_permissions = _required_permission_codes(proposal.action_type, proposal.permission_code)
    if user.status != "ACTIVE" or ("SYS_ADMIN" not in roles and not required_permissions <= permission_codes):
        availability = "PERMISSION_REVOKED"
        reason = "当前账号已无此动作的写入权限"

    if proposal.status == "PENDING" and proposal.expires_at <= _now():
        proposal.status = "EXPIRED"
        changed = True
        reason = "提案已过期，请重新生成"
    elif proposal.status == "PENDING" and availability == "AVAILABLE":
        try:
            action_handlers.get_handler(proposal.action_type).validate_current(db, user, proposal, for_update=False)
        except ResourceNotFoundError:
            proposal.status = "INVALIDATED"
            availability = "RESOURCE_UNAVAILABLE"
            reason = "关联单据已不可访问"
            changed = True
        except BusinessValidationError:
            proposal.status = "INVALIDATED"
            reason = "关联资源或状态已变化，请重新生成提案"
            changed = True

    readable_reference = None
    source_route = None
    resource_visible = False
    if proposal.action_type in {"purchase_request.update_draft", "purchase_request.submit", "rfq.create_draft"}:
        if "SYS_ADMIN" in roles or "procurement.requests.read" in permission_codes:
            try:
                from app.modules.purchase_requests import service as request_service

                if proposal.action_type == "rfq.create_draft":
                    request_id = int(proposal.payload["source_request_id"])
                else:
                    request_id = int(proposal.resource_id or proposal.payload["request_id"])
                request = request_service.get_request(db, user, request_id)
                readable_reference = request.request_no
                source_route = f"/procurement/requests?ai_record_id={request.id}"
                resource_visible = True
            except (KeyError, TypeError, ValueError, ResourceNotFoundError):
                availability = "RESOURCE_UNAVAILABLE"
                reason = "关联单据已不可访问"
        else:
            if availability != "PERMISSION_REVOKED":
                availability = "RESOURCE_UNAVAILABLE"
                reason = "当前账号没有查看关联采购申请的权限"

    base = _preview(proposal).model_dump()
    if proposal.action_type == "rfq.create_draft" and "SYS_ADMIN" not in roles and "master.suppliers.read" not in permission_codes:
        base["evidence"] = [entry for entry in base["evidence"] if entry.get("type") != "suppliers"]
        base["diff"] = [entry for entry in base["diff"] if entry.get("field") != "suppliers"]
    if not resource_visible:
        base["diff"] = []
        base["evidence"] = []
    can_confirm = (
        proposal.status == "PENDING"
        and availability == "AVAILABLE"
        and not proposal.blockers
        and proposal.expires_at > _now()
    )
    result = AIActionProposalRead(
        **base,
        created_at=proposal.created_at,
        business_reference=readable_reference,
        source_route=source_route,
        availability=availability,
        unavailable_reason=reason,
        revision_values=(
            {key: value for key, value in proposal.payload.get("changes", {}).items()
             if key in {"purpose", "priority", "budget_amount", "currency_code", "expected_date"}}
            if proposal.action_type == "purchase_request.update_draft"
            else {key: proposal.payload.get(key) for key in
                  ("quote_deadline", "requested_delivery_date", "delivery_requirements")}
            if proposal.action_type == "rfq.create_draft"
            else {}
        ),
        requires_user_confirmation=can_confirm,
    )
    return result, changed


def list_action_proposals(db: Session, user: User, *, page: int, page_size: int,
                          inbox_only: bool) -> AIActionProposalPage:
    query = select(AIAgentActionProposal).where(
        AIAgentActionProposal.user_id == user.id,
        AIAgentActionProposal.action_type.in_(INBOX_ACTION_TYPES),
    )
    count_query = select(func.count(AIAgentActionProposal.id)).where(
        AIAgentActionProposal.user_id == user.id,
        AIAgentActionProposal.action_type.in_(INBOX_ACTION_TYPES),
    )
    if inbox_only:
        visible_statuses = ("PENDING", "EXPIRED", "INVALIDATED")
        query = query.where(AIAgentActionProposal.status.in_(visible_statuses))
        count_query = count_query.where(AIAgentActionProposal.status.in_(visible_statuses))
    total = db.scalar(count_query) or 0
    proposals = list(db.scalars(query.order_by(AIAgentActionProposal.created_at.desc())
                                .offset((page - 1) * page_size).limit(page_size)))
    items = []
    changed = False
    for proposal in proposals:
        item, item_changed = _proposal_read(db, user, proposal)
        items.append(item)
        changed = changed or item_changed
    if changed:
        db.commit()
    return AIActionProposalPage(items=items, total=total)


def get_action_proposal(db: Session, user: User, confirmation_id: str) -> AIActionProposalRead:
    proposal = _owned_proposal(db, user, confirmation_id, for_update=False)
    result, changed = _proposal_read(db, user, proposal)
    if changed:
        db.commit()
    return result


def revise_action(db: Session, user: User, confirmation_id: str, preview_version: int, payload: dict) -> AIActionProposalPreview:
    proposal = _owned_proposal(db, user, confirmation_id)
    handler = action_handlers.get_handler(proposal.action_type)
    _authorize(db, user, proposal.permission_code, action_type=proposal.action_type)
    if proposal.status != "PENDING" or proposal.expires_at <= _now():
        raise DuplicateResourceError("动作提案已失效，请重新生成")
    if proposal.preview_version != preview_version:
        raise DuplicateResourceError("动作提案版本已变化，请刷新后重试")
    if proposal.action_type == "purchase_request.update_draft" and set(payload) == {"changes"}:
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            raise BusinessValidationError("修改内容格式无效")
        payload = {"request_id": int(proposal.resource_id),
                   "changes": {**proposal.payload.get("changes", {}), **changes}}
    elif proposal.action_type == "rfq.create_draft" and set(payload) <= {
        "quote_deadline", "requested_delivery_date", "delivery_requirements"
    }:
        payload = {**proposal.payload, **payload}
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
    _authorize(db, user, proposal.permission_code, action_type=proposal.action_type)
    if proposal.status != "PENDING" or proposal.expires_at <= _now():
        raise DuplicateResourceError("动作提案已失效")
    if proposal.preview_version != preview_version:
        raise DuplicateResourceError("动作提案版本已变化")
    proposal.status = "CANCELLED"
    db.commit()


def confirm_action(db: Session, user: User, data: AIActionProposalConfirm) -> dict:
    proposal = _owned_proposal(db, user, data.confirmation_id)
    handler = action_handlers.get_handler(proposal.action_type)
    _authorize(db, user, proposal.permission_code, action_type=proposal.action_type)
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
