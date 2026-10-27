"""提案版本、权限复核和领域执行的事务边界。"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai import action_handlers, purchase_draft_bridge as bridge_module
from app.modules.ai.model import AIAgentActionProposal
from app.modules.ai.schema import (AIActionProposalConfirm, AIActionProposalPage, AIActionProposalPreview,
                                   AIActionProposalRead)
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


PROPOSAL_NOTIFICATION_LABELS = {
    "purchase_request.create_draft": "采购申请", "purchase_request.update_draft": "采购申请修改",
    "purchase_request.submit": "采购申请提交", "rfq.create_draft": "询价草稿",
    "rfq.send": "询价发送", "rfq.select_quote": "报价中选",
    "purchase_order.create_draft": "采购订单草稿", "purchase_order.submit": "采购订单提交审批",
    "exceptions.create_task": "异常处理任务", "inventory.create_replenishment": "补货申请",
    "deliveries.followup_draft": "交期催办草稿",
}

INBOX_ACTION_TYPES = ("purchase_request.create_draft", "purchase_request.update_draft", "purchase_request.submit", "rfq.create_draft", "rfq.send", "rfq.select_quote", "purchase_order.create_draft", "purchase_order.submit", "exceptions.create_task", "inventory.create_replenishment", "deliveries.followup_draft")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _required_permission_codes(action_type: str, permission_code: str) -> set[str]:
    return action_handlers.required_permissions(action_type)


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


def propose_action(db: Session, user: User, action_type: str, payload: dict, *, idempotency_key: str, evidence: list[dict] | None = None) -> AIActionProposalPreview:
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
        evidence=evidence if evidence is not None else prepared.get("evidence", []),
        warnings=prepared.get("warnings", []),
        blockers=[],
        permission_code=handler.permission_code,
        risk_level=prepared.get("risk_level", "LOW"),
        idempotency_key=idempotency_key,
        expires_at=_now() + timedelta(minutes=10),
        status="PENDING",
    )
    db.add(proposal)
    if action_type in INBOX_ACTION_TYPES:
        # 同一事务创建提醒；重放幂等键走上面的已有提案分支，不重复发通知。
        from app.modules.notifications.model import Notification
        db.flush()
        db.add(Notification(recipient_id=user.id, notification_type="AI_PROPOSAL_PENDING",
            title=f"{PROPOSAL_NOTIFICATION_LABELS.get(action_type, '动作')}提案待确认", content="您有一项动作提案待核对，请查看详情。",
            related_type="AI_ACTION_PROPOSAL", related_id=proposal.id))
    db.commit()
    return _preview(proposal)


def _owned_proposal(db: Session, user: User, confirmation_id: str, *, for_update: bool = True) -> AIAgentActionProposal:
    query = select(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == confirmation_id,
        AIAgentActionProposal.user_id == user.id,
    ).execution_options(populate_existing=True)
    proposal = db.scalar(query.with_for_update() if for_update else query)
    if proposal is None:
        raise ResourceNotFoundError("动作提案不存在或不属于当前用户")
    return proposal


def _revalidate_tool_evidence(db: Session, user: User, proposal: AIAgentActionProposal) -> None:
    """确认前按当前权限重放只读来源；事实或权限变化时要求重新预览。

    不放在写事务内：先复核来源，再锁提案并复查版本，避免长时间持有业务行锁。
    产品目录定位结果由提案快照中的产品状态/版本校验，不重复比较搜索排名。
    """

    from app.modules.ai import agent_tools
    from app.modules.ai.purchase_draft_bridge import result_fingerprint
    from app.modules.ai.schema import ToolCall
    from app.modules.ai.tool_sql_timeout import ToolTimeoutUnsupported

    for entry in proposal.evidence or []:
        if not isinstance(entry, dict) or entry.get("type") != "tool":
            continue
        tool = entry.get("tool")
        arguments = entry.get("arguments")
        if tool == "catalog.search_products":
            continue
        if not isinstance(tool, str) or not isinstance(arguments, dict) or not entry.get("fingerprint"):
            raise BusinessValidationError("来源证据格式无效，请重新生成预览")
        try:
            result = agent_tools.execute_tool(db, user, ToolCall(tool=tool, arguments=arguments))
        except AuthorizationError as exc:
            raise BusinessValidationError("来源数据读取权限已变化，请重新生成预览") from exc
        except (BusinessValidationError, ResourceNotFoundError, TimeoutError, ToolTimeoutUnsupported) as exc:
            raise BusinessValidationError("来源事实暂时无法核验，请稍后重新生成预览") from exc
        if result_fingerprint(result.model_dump(mode="json")) != entry.get("fingerprint"):
            raise BusinessValidationError("来源事实已变化，请重新核对预览后再确认")


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
        reason = "当前账号已无此动作所需的读写权限"

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
    if proposal.action_type == "purchase_request.create_draft":
        resource_visible = ("SYS_ADMIN" in roles or "procurement.requests.write" in permission_codes)
        if resource_visible:
            readable_reference = "待创建采购申请"
    elif proposal.action_type == "exceptions.create_task":
        if "SYS_ADMIN" in roles or "operations.exceptions.read" in permission_codes:
            try:
                from app.modules.operation_exceptions import service as exception_service

                exception = exception_service.get_exception_for_task_creation(
                    db, user, int(proposal.resource_id))
                readable_reference = exception.exception_no
                source_route = "/operations/exceptions"
                resource_visible = True
            except (TypeError, ValueError, BusinessValidationError, ResourceNotFoundError):
                availability = "RESOURCE_UNAVAILABLE"
                reason = "关联异常已不可访问"
        elif availability != "PERMISSION_REVOKED":
            availability = "RESOURCE_UNAVAILABLE"
            reason = "当前账号没有查看关联异常的权限"
    elif proposal.action_type in {"purchase_order.submit", "deliveries.followup_draft"}:
        may_show_draft = proposal.action_type != "deliveries.followup_draft" or availability != "PERMISSION_REVOKED"
        if may_show_draft and ("SYS_ADMIN" in roles or "procurement.orders.read" in permission_codes):
            try:
                from app.modules.purchase_orders import service as purchase_order_service

                order = purchase_order_service.get_order(db, user, int(proposal.resource_id))
                readable_reference = order.po_no
                source_route = f"/procurement/orders/{order.id}"
                if proposal.action_type == 'deliveries.followup_draft' and proposal.status == 'EXECUTED':
                    source_route += f'?followup_proposal={proposal.confirmation_id}'
                resource_visible = True
            except (TypeError, ValueError, BusinessValidationError, ResourceNotFoundError):
                availability = "RESOURCE_UNAVAILABLE"
                reason = "关联采购订单已不可访问"
        elif availability != "PERMISSION_REVOKED":
            availability = "RESOURCE_UNAVAILABLE"
            reason = "当前账号没有查看关联采购订单的权限"
    elif proposal.action_type == "inventory.create_replenishment":
        if proposal.status == "EXECUTED" and proposal.result:
            if "SYS_ADMIN" in roles or "procurement.replenishment.read" in permission_codes:
                try:
                    from app.modules.replenishments import service as replenishment_service

                    value = replenishment_service.get_replenishment(db, user, int(proposal.result["id"]))
                    readable_reference = value.replenishment_no
                    source_route = f"/procurement/replenishments?ai_record_id={value.id}"
                    resource_visible = True
                except (KeyError, TypeError, ValueError, BusinessValidationError, ResourceNotFoundError):
                    availability = "RESOURCE_UNAVAILABLE"
                    reason = "关联补货申请已不可访问"
            elif availability != "PERMISSION_REVOKED":
                availability = "RESOURCE_UNAVAILABLE"
                reason = "当前账号没有查看关联补货申请的权限"
        else:
            resource_visible = ("SYS_ADMIN" in roles or "procurement.replenishment.write" in permission_codes)
            if resource_visible:
                readable_reference = "待创建补货申请"
    elif proposal.action_type in {"purchase_request.update_draft", "purchase_request.submit", "rfq.create_draft", "rfq.send", "rfq.select_quote", "purchase_order.create_draft"}:
        resource_read_permission = "procurement.rfqs.read" if proposal.action_type in {"rfq.send", "rfq.select_quote", "purchase_order.create_draft"} else "procurement.requests.read"
        if "SYS_ADMIN" in roles or resource_read_permission in permission_codes:
            try:
                from app.modules.purchase_requests import service as request_service

                if proposal.action_type in {"rfq.send", "rfq.select_quote", "purchase_order.create_draft"}:
                    from app.modules.rfqs import service as rfq_service

                    rfq = rfq_service.get_rfq(db, user, int(proposal.resource_id))
                    readable_reference = rfq.rfq_no
                    source_route = f"/procurement/rfqs?ai_record_id={rfq.id}"
                    resource_visible = True
                    request_id = None
                elif proposal.action_type == "rfq.create_draft":
                    request_id = int(proposal.payload["source_request_id"])
                elif proposal.action_type == "purchase_order.create_draft":
                    request_id = None
                else:
                    request_id = int(proposal.resource_id or proposal.payload["request_id"])
                if request_id is not None:
                    request = request_service.get_request(db, user, request_id)
                    readable_reference = request.request_no
                    source_route = f"/procurement/requests?ai_record_id={request.id}"
                    resource_visible = True
            except (KeyError, TypeError, ValueError, BusinessValidationError, ResourceNotFoundError):
                availability = "RESOURCE_UNAVAILABLE"
                reason = "关联单据已不可访问"
        else:
            if availability != "PERMISSION_REVOKED":
                availability = "RESOURCE_UNAVAILABLE"
                reason = "当前账号没有查看关联询价单的权限" if proposal.action_type in {"rfq.send", "rfq.select_quote", "purchase_order.create_draft"} else "当前账号没有查看关联采购申请的权限"

    base = _preview(proposal).model_dump()
    if proposal.action_type == "rfq.create_draft" and "SYS_ADMIN" not in roles and "master.suppliers.read" not in permission_codes:
        base["evidence"] = [entry for entry in base["evidence"] if entry.get("type") != "suppliers"]
        base["diff"] = [entry for entry in base["diff"] if entry.get("field") != "suppliers"]
    if not resource_visible:
        base["diff"] = []
        base["evidence"] = []
    elif base["evidence"]:
        readable_evidence = [entry for entry in base["evidence"]
                             if bridge_module.evidence_readable(entry, permission_codes, roles)]
        if len(readable_evidence) != len(base["evidence"]):
            base["evidence"] = readable_evidence
            if proposal.action_type == "purchase_request.create_draft" and availability == "AVAILABLE":
                availability = "PERMISSION_REVOKED"
                reason = "当前账号已无查看来源库存或报价所需的权限"
        else:
            base["evidence"] = readable_evidence
    can_confirm = (
        proposal.status == "PENDING"
        and availability == "AVAILABLE"
        and not proposal.blockers
        and proposal.expires_at > _now()
    )
    base["requires_user_confirmation"] = can_confirm
    revision_values = {}
    if proposal.action_type == "purchase_request.update_draft":
        revision_values = {key: value for key, value in proposal.payload.get("changes", {}).items()
                          if key in {"purpose", "priority", "budget_amount", "currency_code", "expected_date"}}
    elif proposal.action_type == "rfq.create_draft":
        revision_values = {key: proposal.payload.get(key) for key in
                           ("quote_deadline", "requested_delivery_date", "delivery_requirements")}
    elif proposal.action_type == "rfq.select_quote":
        revision_values = {"selection_reason": proposal.payload.get("selection_reason")}
    elif proposal.action_type == "purchase_order.create_draft":
        revision_values = {key: proposal.payload.get(key) for key in
                           ("delivery_address", "expected_arrival_date", "note")}
    elif proposal.action_type == "deliveries.followup_draft" and proposal.status == "PENDING":
        revision_values = {"followup_note": proposal.payload.get("followup_note", "")}
    if not resource_visible:
        revision_values = {}
    result = AIActionProposalRead(
        **base,
        created_at=proposal.created_at,
        business_reference=readable_reference,
        source_route=source_route,
        availability=availability,
        unavailable_reason=reason,
        revision_values=revision_values,
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
    elif proposal.action_type == "rfq.select_quote" and set(payload) == {"selection_reason"}:
        payload = {**proposal.payload, **payload}
    elif proposal.action_type == "purchase_order.create_draft" and set(payload) <= {
        "delivery_address", "expected_arrival_date", "note"
    }:
        payload = {**proposal.payload, **payload}
    elif proposal.action_type == "deliveries.followup_draft":
        if set(payload) != {"followup_note"}:
            raise BusinessValidationError("交期跟进草稿仅可修改补充说明，不能更换订单或覆盖业务事实")
        payload = {**proposal.payload, **payload}
    prepared = handler.prepare(db, user, payload)
    if prepared.get("blockers"):
        raise BusinessValidationError("动作提案存在阻塞项，不能保存为可确认预览")
    if proposal.action_type == "rfq.select_quote":
        prepared["diff"] = [
            {**item, "before": proposal.payload.get("selection_reason")}
            if item.get("field") == "selection_reason" else item
            for item in prepared.get("diff", [])
        ]
    if proposal.action_type == "purchase_request.create_draft":
        previous_products = {item.get("product_id") for item in proposal.payload.get("items", [])
                             if isinstance(item, dict)}
        next_products = {item.get("product_id") for item in prepared["payload"].get("items", [])
                         if isinstance(item, dict)}
        if previous_products != next_products:
            # 产品改变后旧库存/报价证据不再相关；确认时会重新校验剩余来源。
            proposal.evidence = []
    proposal.payload = prepared["payload"]
    proposal.payload_hash = _hash(proposal.payload)
    proposal.expected_resource_snapshot = prepared.get("snapshot", {})
    proposal.diff = prepared.get("diff", [])
    if proposal.action_type != "purchase_request.create_draft":
        proposal.evidence = prepared.get("evidence", []) or proposal.evidence or []
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


def _read_executed_result(db: Session, user: User, proposal: AIAgentActionProposal) -> dict:
    # 草稿正文属于订单数据；幂等重放也须校验当前资源范围，不能只检查动作权限。
    if proposal.action_type == "deliveries.followup_draft":
        from app.modules.purchase_orders import service as order_service

        order_service.get_order(db, user, int(proposal.resource_id))
    return proposal.result or {}


def confirm_action(db: Session, user: User, data: AIActionProposalConfirm) -> dict:
    proposal = _owned_proposal(db, user, data.confirmation_id, for_update=False)
    handler = action_handlers.get_handler(proposal.action_type)
    _authorize(db, user, proposal.permission_code, action_type=proposal.action_type)
    if proposal.status == "EXECUTED":
        return _read_executed_result(db, user, proposal)
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
    # 来源核验放在加锁前：工具查询可能耗时，不占用业务行锁。
    _revalidate_tool_evidence(db, user, proposal)
    proposal = _owned_proposal(db, user, data.confirmation_id)
    _authorize(db, user, proposal.permission_code, action_type=proposal.action_type)
    if proposal.status == "EXECUTED":
        return _read_executed_result(db, user, proposal)
    if proposal.preview_version != data.preview_version or proposal.status != "PENDING":
        raise DuplicateResourceError("动作提案已变化，请重新核对")
    if proposal.expires_at <= _now():
        proposal.status = "EXPIRED"
        db.commit()
        raise DuplicateResourceError("动作提案已过期，请重新生成")
    if _hash(proposal.payload) != proposal.payload_hash:
        raise BusinessValidationError("动作提案参数校验失败，请重新生成")
    action_handlers.get_handler(proposal.action_type).validate_current(db, user, proposal)
    result = handler.execute(db, user, proposal, commit=False)
    proposal.status = "EXECUTED"
    proposal.result = result
    proposal.executed_at = _now()
    db.commit()
    return result
