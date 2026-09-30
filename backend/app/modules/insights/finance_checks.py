"""Human review of line receipts and order-level finance documents."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.insights.checks import CheckItemUpdate
from app.modules.insights.model import FinanceDifferenceCheck, FinanceDifferenceEvent, InsightSnapshot
from app.modules.purchase_orders import service as order_service
from app.modules.purchase_orders.model import PurchaseOrderItem
from app.modules.system import crud as system_crud
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User


class FinanceCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    scope_key: str
    target_label: str
    snapshot_id: int
    assignee_id: int | None
    status: str
    finding: str | None
    checked_by: int | None
    checked_at: datetime | None
    reviewed_by: int | None
    reviewed_at: datetime | None


class FinanceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    check_id: int
    actor_id: int
    status: str
    assignee_id: int | None
    finding: str | None
    created_at: datetime


def _can_handle(db: Session, user: User, order_id: int) -> bool:
    permissions = system_crud.get_user_permission_codes(db, user.id)
    if "SYS_ADMIN" not in system_crud.get_user_role_codes(db, user.id) and "finance.reconciliations.write" not in permissions:
        return False
    try:
        order_service.get_order(db, user, order_id)
    except ResourceNotFoundError:
        return False
    return True


def list_checks(db: Session, user: User, order_id: int) -> list[FinanceDifferenceCheck]:
    order_service.get_order(db, user, order_id)
    return list(db.scalars(select(FinanceDifferenceCheck).where(FinanceDifferenceCheck.order_id == order_id).order_by(FinanceDifferenceCheck.id)).all())


def list_assignees(db: Session, user: User, order_id: int) -> list[dict[str, int | str]]:
    order_service.get_order(db, user, order_id)
    return [{"id": person.id, "name": person.display_name} for person in db.scalars(select(User).where(User.status == "ACTIVE").order_by(User.display_name)).all() if _can_handle(db, person, order_id)]


def create_checks(db: Session, user: User, order_id: int, snapshot_id: int) -> list[FinanceDifferenceCheck]:
    order = order_service.get_order(db, user, order_id)
    snapshot = db.get(InsightSnapshot, snapshot_id)
    if snapshot is None or snapshot.created_by != user.id or snapshot.kind != "finance-difference" or snapshot.object_id != order.id:
        raise BusinessValidationError("请先保存当前财务差异分析")
    scopes = [(f"LINE:{line.id}", f"订单行 {line.line_no} · {line.product_name_snapshot}") for line in db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == order.id).order_by(PurchaseOrderItem.line_no)).all()]
    scopes.append(("DOCUMENTS", "对账、发票、付款及结算单据"))
    for key, label in scopes:
        exists = db.scalar(select(FinanceDifferenceCheck.id).where(FinanceDifferenceCheck.order_id == order.id, FinanceDifferenceCheck.scope_key == key))
        if exists is None:
            db.add(FinanceDifferenceCheck(order_id=order.id, scope_key=key, target_label=label, snapshot_id=snapshot.id))
    try:
        db.flush()
        add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="FINANCE_DIFFERENCE_CHECK", resource_id=order.id, request_summary="建立财务差异核查清单", result_status="SUCCESS")
        db.commit()
    except IntegrityError:
        db.rollback()
    return list_checks(db, user, order_id)


def list_events(db: Session, user: User, order_id: int, check_id: int) -> list[FinanceDifferenceEvent]:
    if check_id not in {item.id for item in list_checks(db, user, order_id)}:
        raise ResourceNotFoundError("财务核查项不存在")
    return list(db.scalars(select(FinanceDifferenceEvent).where(FinanceDifferenceEvent.check_id == check_id).order_by(FinanceDifferenceEvent.id)).all())


def update_check(db: Session, user: User, order_id: int, check_id: int, data: CheckItemUpdate) -> FinanceDifferenceCheck:
    order_service.get_order(db, user, order_id)
    item = db.scalar(select(FinanceDifferenceCheck).where(FinanceDifferenceCheck.id == check_id, FinanceDifferenceCheck.order_id == order_id).with_for_update())
    if item is None:
        raise ResourceNotFoundError("财务核查项不存在")
    values = data.model_dump(exclude_unset=True)
    if not values:
        raise BusinessValidationError("没有需要更新的核查内容")
    if "assignee_id" in values:
        person = db.get(User, data.assignee_id) if data.assignee_id else None
        if data.assignee_id is not None and (person is None or person.status != "ACTIVE" or not _can_handle(db, person, order_id)):
            raise BusinessValidationError("核查负责人没有该订单的财务处理权限")
        item.assignee_id = data.assignee_id
    if data.status is not None:
        allowed = {"OPEN": {"CHECKED", "NEEDS_ACTION"}, "CHECKED": {"VERIFIED", "NEEDS_ACTION", "OPEN"}, "NEEDS_ACTION": {"CHECKED", "OPEN"}, "VERIFIED": {"OPEN"}}
        if data.status not in allowed.get(item.status, set()):
            raise BusinessValidationError("财务核查项状态不能这样变更")
        if data.status != "OPEN" and not (data.finding or item.finding):
            raise BusinessValidationError("提交核查结果前请填写说明")
        if data.status in {"CHECKED", "NEEDS_ACTION"} and item.assignee_id not in {None, user.id}:
            raise BusinessValidationError("仅指派人员可提交核查结果")
        if data.status == "VERIFIED" and (item.status != "CHECKED" or item.checked_by == user.id):
            raise BusinessValidationError("复核人须与核查人不同，且核查项已提交")
        item.status = data.status
        if data.status == "VERIFIED":
            item.reviewed_by = user.id
            item.reviewed_at = datetime.now()
        elif data.status in {"CHECKED", "NEEDS_ACTION"}:
            item.checked_by = user.id
            item.checked_at = datetime.now()
            item.reviewed_by = None
            item.reviewed_at = None
        else:
            item.checked_by = None
            item.checked_at = None
            item.reviewed_by = None
            item.reviewed_at = None
    if "finding" in values:
        item.finding = data.finding
    db.add(FinanceDifferenceEvent(check_id=item.id, actor_id=user.id, status=item.status, assignee_id=item.assignee_id, finding=item.finding))
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="FINANCE_DIFFERENCE_CHECK", resource_id=item.id, request_summary=f"财务差异核查项状态 {item.status}", result_status="SUCCESS")
    db.commit()
    db.refresh(item)
    return item
