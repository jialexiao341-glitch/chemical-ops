"""采购申请草稿的显式确认、一次性消费和原子领域写入。"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.ai.model import AIPurchaseDraftConfirmation
from app.modules.ai.schema import AIPurchaseDraftConfirm
from app.modules.products.model import Product
from app.modules.purchase_requests import service as purchase_request_service
from app.modules.purchase_requests.model import Unit
from app.modules.purchase_requests.schema import PurchaseRequestCreate, PurchaseRequestRead
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def confirm_purchase_draft(db: Session, user: User, data: AIPurchaseDraftConfirm) -> dict:
    """在单个 MySQL 事务中消费确认快照并经采购领域服务创建 DRAFT。"""
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
