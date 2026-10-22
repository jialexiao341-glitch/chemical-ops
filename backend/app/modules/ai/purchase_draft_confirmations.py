"""采购申请草稿的显式确认、一次性消费和原子领域写入。"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai.model import AIAgentActionProposal, AIPurchaseDraftConfirmation
from app.modules.ai.schema import (AIActionProposalConfirm, AIPurchaseDraftConfirm, AIPurchaseDraftPatch,
                                   AIPurchaseDraftPreview, AIPurchaseDraftPreviewItem)
from app.modules.products.model import Product
from app.modules.purchase_requests import service as purchase_request_service
from app.modules.purchase_requests.model import Unit
from app.modules.purchase_requests.schema import PurchaseRequestCreate, PurchaseRequestRead
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User
from app.modules.products.model import Product


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def confirm_purchase_draft(db: Session, user: User, data: AIPurchaseDraftConfirm) -> dict:
    """在单个 MySQL 事务中消费确认快照并经采购领域服务创建 DRAFT。"""
    generic = db.scalar(select(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == data.confirmation_id,
        AIAgentActionProposal.user_id == user.id,
    ))
    if isinstance(generic, AIAgentActionProposal):
        from app.modules.ai.action_proposals import confirm_action
        return confirm_action(db, user, AIActionProposalConfirm(
            confirmation_id=data.confirmation_id, preview_version=data.preview_version, confirm=data.confirm
        ))
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if user.status != "ACTIVE" or ("SYS_ADMIN" not in roles and "procurement.requests.write" not in permissions):
        raise AuthorizationError("当前账号没有创建采购申请草稿的权限")

    confirmation = db.scalar(select(AIPurchaseDraftConfirmation).where(
        AIPurchaseDraftConfirmation.confirmation_id == data.confirmation_id,
        AIPurchaseDraftConfirmation.user_id == user.id,
    ).with_for_update())
    if confirmation is None:
        raise ResourceNotFoundError("采购申请预览不存在或不属于当前用户，请重新生成预览")
    if confirmation.preview_version != data.preview_version:
        raise DuplicateResourceError("采购申请预览版本已变化，请重新核对")
    if confirmation.status == "EXECUTED":
        return confirmation.result or {}
    if confirmation.status != "PENDING":
        raise DuplicateResourceError("该采购申请预览已失效，请重新生成")
    if confirmation.expires_at <= _now():
        confirmation.status = "EXPIRED"
        db.commit()
        raise DuplicateResourceError("采购申请预览已过期，请重新生成并核对")

    payload = confirmation.draft_payload
    if _hash(payload) != confirmation.request_hash:
        raise BusinessValidationError("采购申请预览参数校验失败，请重新生成")
    if confirmation.object_versions.get("actor_department_id") != user.department_id:
        raise DuplicateResourceError("当前用户所属部门已变化，请重新生成并核对预览")
    try:
        draft = PurchaseRequestCreate.model_validate(payload)
    except Exception as exc:
        raise BusinessValidationError("采购申请预览参数已变化或无效，请重新生成") from exc

    for product_id, saved in confirmation.object_versions.get("products", {}).items():
        product = db.scalar(select(Product).where(Product.id == int(product_id)).with_for_update())
        if product is None or product.status != saved["status"] or product.version_no != saved["version_no"] or product.status != "ACTIVE":
            raise DuplicateResourceError("关联产品状态或版本已变化，请重新查询并核对预览")
    for unit_id, saved in confirmation.object_versions.get("units", {}).items():
        unit = db.scalar(select(Unit).where(Unit.id == int(unit_id)).with_for_update())
        if unit is None or unit.status != "ACTIVE" or unit.unit_name != saved["unit_name"] or unit.dimension != saved["dimension"]:
            raise DuplicateResourceError("计量单位状态或信息已变化，请重新查询并核对预览")

    # 领域服务只 flush；确认账本与申请、明细、审计日志一起提交。
    request = purchase_request_service.create_request(db, user, draft, commit=False)
    result = PurchaseRequestRead.model_validate(request).model_dump(mode="json")
    confirmation.status = "EXECUTED"
    confirmation.purchase_request_id = request.id
    confirmation.result = result
    confirmation.executed_at = _now()
    db.commit()
    return result


def patch_purchase_draft(db: Session, user: User, data: AIPurchaseDraftPatch) -> AIPurchaseDraftPreview:
    """只修改本人 PENDING 快照；刷新对象版本/哈希并递增预览版本，需显式重确认。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if user.status != "ACTIVE" or ("SYS_ADMIN" not in roles and "procurement.requests.write" not in permissions):
        raise AuthorizationError("当前账号没有修改采购申请草稿的权限")
    allowed = {"purpose", "priority", "budget_amount", "currency_code", "expected_date", "items"}
    if set(data.changes) - allowed:
        raise BusinessValidationError("草稿修改包含不允许的字段")
    generic = db.scalar(select(AIAgentActionProposal).where(
        AIAgentActionProposal.confirmation_id == data.confirmation_id,
        AIAgentActionProposal.user_id == user.id,
    ))
    if isinstance(generic, AIAgentActionProposal):
        from app.modules.ai.action_proposals import revise_action
        revised_payload = {**generic.payload, **data.changes}
        preview = revise_action(db, user, data.confirmation_id, data.preview_version, revised_payload)
        displays = []
        for item in revised_payload["items"]:
            product = db.get(Product, item.get("product_id")) if item.get("product_id") else None
            unit = db.get(Unit, item["unit_id"])
            displays.append(AIPurchaseDraftPreviewItem(
                requested_name=item["requested_name"], product_name=product.product_name if product else None,
                quantity=str(item["quantity"]), unit_name=unit.unit_name if unit else "",
                technical_requirements=item.get("technical_requirements"),
                budget_price=str(item["budget_price"]) if item.get("budget_price") is not None else None,
            ))
        return AIPurchaseDraftPreview(draft=revised_payload, display_items=displays,
            warnings=preview.warnings, evidence=preview.evidence, confirmation_id=preview.confirmation_id,
            preview_version=preview.preview_version, expires_at=preview.expires_at, requires_user_confirmation=True)
    confirmation = db.scalar(select(AIPurchaseDraftConfirmation).where(
        AIPurchaseDraftConfirmation.confirmation_id == data.confirmation_id,
        AIPurchaseDraftConfirmation.user_id == user.id).with_for_update())
    if confirmation is None:
        raise ResourceNotFoundError("采购申请预览不存在或不属于当前用户")
    if confirmation.status != "PENDING" or confirmation.expires_at <= _now():
        raise DuplicateResourceError("预览已失效，请重新生成")
    if confirmation.preview_version != data.preview_version or _hash(confirmation.draft_payload) != confirmation.request_hash:
        raise DuplicateResourceError("预览版本已变化，请刷新后重试")
    if confirmation.object_versions.get("actor_department_id") != user.department_id:
        raise DuplicateResourceError("用户部门已变化，请重新生成预览")
    payload = {**confirmation.draft_payload, **data.changes}
    if payload.get("department_id") != user.department_id:
        raise BusinessValidationError("申请部门由当前用户身份确定，不能通过草稿修改")
    try:
        draft = PurchaseRequestCreate.model_validate(payload)
    except Exception as exc:
        raise BusinessValidationError("草稿修改未通过申请字段校验") from exc
    products = {}
    units = {}
    for item in draft.items:
        unit = db.scalar(select(Unit).where(Unit.id == item.unit_id).with_for_update())
        if unit is None or unit.status != "ACTIVE":
            raise DuplicateResourceError("计量单位已停用或不存在，请重新选择")
        units[str(unit.id)] = {"unit_name": unit.unit_name, "dimension": unit.dimension}
        if item.product_id is not None:
            product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
            if product is None or product.status != "ACTIVE":
                raise DuplicateResourceError("产品已停用或不存在，请重新选择")
            old = confirmation.object_versions.get("products", {}).get(str(product.id))
            if old is None or old != {"version_no": product.version_no, "status": product.status}:
                # 新关联必须来自当前用户可访问的产品目录检索，不接受用户直接提交 ID。
                from app.modules.ai import agent_tools
                catalog = {entry["name"] for entry in agent_tools.list_tools(db, user)}
                if "catalog.search_products" not in catalog:
                    raise AuthorizationError("当前权限不能检索产品目录")
                from app.modules.ai.schema import ToolCall
                found = agent_tools.execute_tool(db, user, ToolCall(tool="catalog.search_products",
                    arguments={"keyword": item.requested_name, "limit": 100}))
                if product.id not in {row.product_id for row in found.rows}:
                    raise BusinessValidationError("产品必须来自当前授权目录候选")
            products[str(product.id)] = {"version_no": product.version_no, "status": product.status}
    snapshot = draft.model_dump(mode="json")
    confirmation.draft_payload = snapshot
    confirmation.request_hash = _hash(snapshot)
    confirmation.object_versions = {"actor_department_id": user.department_id, "products": products, "units": units}
    confirmation.preview_version += 1
    confirmation.evidence = [*confirmation.evidence, {"type": "draft_edit", "fields": sorted(data.changes)}]
    displays = []
    for item in draft.items:
        product = db.get(Product, item.product_id) if item.product_id else None
        unit = db.get(Unit, item.unit_id)
        displays.append(AIPurchaseDraftPreviewItem(requested_name=item.requested_name,
            product_name=product.product_name if product else None, quantity=str(item.quantity),
            unit_name=unit.unit_name, technical_requirements=item.technical_requirements,
            budget_price=str(item.budget_price) if item.budget_price is not None else None))
    db.commit()
    return AIPurchaseDraftPreview(draft=snapshot, display_items=displays,
        evidence=confirmation.evidence, confirmation_id=confirmation.confirmation_id,
        preview_version=confirmation.preview_version, expires_at=confirmation.expires_at.replace(tzinfo=timezone.utc),
        requires_user_confirmation=True)
