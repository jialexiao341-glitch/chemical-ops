"""采购申请的业务校验、状态流转和事务处理。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.products.model import Product
from app.modules.purchase_requests import crud
from app.modules.purchase_requests.model import (
    PurchaseRequest,
    PurchaseRequestApproval,
    PurchaseRequestItem,
    Unit,
)
from app.modules.purchase_requests.schema import (
    ApprovalAction,
    CancelAction,
    PurchaseRequestCreate,
    PurchaseRequestUpdate,
)
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import Department, User


def _now() -> datetime:
    """返回数据库使用的无时区当前时间。"""

    return datetime.now()


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以查看和处理全部采购申请。"""

    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER"} & set(get_user_role_codes(db, user.id)))


def _validate_department_scope(db: Session, user: User, department_id: int | None) -> None:
    """阻止普通申请人把申请创建或转移到自身部门范围之外。"""

    if _can_manage_all(db, user):
        return
    if department_id != user.department_id:
        raise ResourceNotFoundError("采购申请部门不存在")


def _require_request(db: Session, request_id: int, *, for_update: bool = False) -> PurchaseRequest:
    """查询采购申请，不存在时抛出业务异常。"""

    request = crud.get_by_id(db, request_id, for_update=for_update)
    if request is None:
        raise ResourceNotFoundError(f"采购申请 {request_id} 不存在")
    return request


def _validate_department(db: Session, department_id: int | None) -> None:
    """校验申请部门存在且处于启用状态。"""

    if department_id is None:
        return
    department = db.scalar(select(Department).where(Department.id == department_id))
    if department is None or department.status != "ACTIVE":
        raise BusinessValidationError(f"申请部门 {department_id} 不存在或已停用")


def _validate_items(db: Session, items) -> None:
    """校验产品、计量单位和明细业务数据。"""

    for item in items:
        if item.product_id is not None:
            product = db.scalar(select(Product).where(Product.id == item.product_id))
            if product is None or product.status != "ACTIVE":
                raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
        unit = db.scalar(select(Unit).where(Unit.id == item.unit_id))
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")


def _audit(db: Session, user_id: int, action: str, request: PurchaseRequest, summary: str) -> None:
    """在当前业务事务中写入审计记录。"""

    from app.modules.system.audit import add_audit_log

    add_audit_log(
        db,
        actor_id=user_id,
        action_type=action,
        resource_type="PURCHASE_REQUEST",
        resource_id=request.id,
        request_summary=f"{request.request_no}: {summary}",
        result_status="SUCCESS",
    )


def create_request(db: Session, user: User, data: PurchaseRequestCreate, *, commit: bool = True) -> PurchaseRequest:
    """创建采购申请草稿和明细。"""

    department_id = data.department_id if data.department_id is not None else user.department_id
    _validate_department_scope(db, user, department_id)
    _validate_department(db, department_id)
    _validate_items(db, data.items)
    request = PurchaseRequest(
        request_no="TEMP",
        applicant_id=user.id,
        department_id=department_id,
        purpose=data.purpose,
        priority=data.priority,
        budget_amount=data.budget_amount,
        currency_code=data.currency_code,
        expected_date=data.expected_date,
        status="DRAFT",
    )
    db.add(request)
    db.flush()
    request.request_no = f"PR{_now():%Y%m%d}{request.id:06d}"
    request.items = [
        PurchaseRequestItem(line_no=index, **item.model_dump())
        for index, item in enumerate(data.items, start=1)
    ]
    db.flush()
    _audit(db, user.id, "CREATE", request, "创建采购申请草稿")
    if commit:
        db.commit()
        db.refresh(request)
        return _require_request(db, request.id)
    return request


def list_requests(
    db: Session,
    user: User,
    *,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[PurchaseRequest], int]:
    """按用户数据范围查询采购申请。"""

    can_manage_all = _can_manage_all(db, user)
    applicant_id = None if can_manage_all or user.department_id is not None else user.id
    department_id = user.department_id if not can_manage_all else None
    return crud.list_page(
        db,
        applicant_id=applicant_id,
        department_id=department_id,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )


def get_request(db: Session, user: User, request_id: int, *, for_update: bool = False) -> PurchaseRequest:
    """查询采购申请详情并执行数据范围校验。"""

    request = _require_request(db, request_id, for_update=for_update)
    if not _can_manage_all(db, user) and not ((user.department_id is not None and request.department_id == user.department_id) or (user.department_id is None and request.applicant_id == user.id)):
        raise ResourceNotFoundError(f"采购申请 {request_id} 不存在")
    return request


def update_request(db: Session, user: User, request_id: int, data: PurchaseRequestUpdate) -> PurchaseRequest:
    """更新草稿或被驳回的采购申请。"""

    request = get_request(db, user, request_id, for_update=True)
    if request.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的采购申请可以修改")
    values = data.model_dump(exclude_unset=True)
    if "department_id" in values:
        _validate_department_scope(db, user, data.department_id)
        _validate_department(db, data.department_id)
    if data.items is not None:
        _validate_items(db, data.items)
        crud.delete_items(db, request.id)
        request.items = [
            PurchaseRequestItem(line_no=index, **item.model_dump())
            for index, item in enumerate(data.items, start=1)
        ]
    for field in ("department_id", "purpose", "priority", "budget_amount", "currency_code", "expected_date"):
        if field in values:
            setattr(request, field, values[field])
    db.flush()
    _audit(db, user.id, "UPDATE", request, "更新采购申请")
    db.commit()
    return _require_request(db, request.id)


def submit_request(db: Session, user: User, request_id: int) -> PurchaseRequest:
    """提交采购申请并创建首个审批节点。"""

    request = get_request(db, user, request_id, for_update=True)
    if request.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的采购申请可以提交")
    if not request.items:
        raise BusinessValidationError("采购申请至少需要一条明细")
    crud.delete_approvals(db, request.id)
    request.status = "APPROVING"
    request.submitted_at = _now()
    request.rejected_at = None
    request.cancelled_at = None
    request.cancel_reason = None
    request.approvals = [
        PurchaseRequestApproval(
            sequence_no=1,
            node_code="PROCUREMENT_MANAGER",
            node_name="采购负责人审批",
            action="PENDING",
        )
    ]
    db.flush()
    _audit(db, user.id, "SUBMIT", request, "提交采购申请审批")
    db.commit()
    return _require_request(db, request.id)


def act_on_request(
    db: Session,
    user: User,
    request_id: int,
    data: ApprovalAction,
    action: str,
) -> PurchaseRequest:
    """处理当前审批节点，并完成采购申请状态流转。"""

    get_request(db, user, request_id)
    request = _require_request(db, request_id, for_update=True)
    if request.applicant_id == user.id:
        raise BusinessValidationError("不能审批本人经办的采购申请")
    approval = crud.get_pending_approval(db, request_id, for_update=True)
    # SUBMITTED 是旧数据和现有数据库种子使用的状态；两者都表示存在待审批节点。
    if request.status not in {"SUBMITTED", "APPROVING"} or approval is None:
        raise BusinessValidationError("采购申请当前没有待处理的审批节点")
    if approval.approver_id is not None and approval.approver_id != user.id:
        raise BusinessValidationError("该审批节点已分配给其他用户")
    approval.approver_id = user.id
    approval.action = action
    approval.opinion = data.opinion
    approval.acted_at = _now()
    if action == "APPROVED":
        request.status = "APPROVED"
        request.approved_at = _now()
        request.rejected_at = None
        summary = "审批通过采购申请"
        audit_action = "APPROVE"
    else:
        request.status = "REJECTED"
        request.rejected_at = _now()
        request.approved_at = None
        summary = "驳回采购申请"
        audit_action = "REJECT"
    db.flush()
    _audit(db, user.id, audit_action, request, summary)
    db.commit()
    return _require_request(db, request.id)


def cancel_request(db: Session, user: User, request_id: int, data: CancelAction) -> PurchaseRequest:
    """取消草稿或已驳回的采购申请。"""

    request = get_request(db, user, request_id, for_update=True)
    if request.status not in {"DRAFT", "REJECTED"}:
        raise BusinessValidationError("只有草稿或已驳回的采购申请可以取消")
    request.status = "CANCELLED"
    request.cancelled_at = _now()
    request.cancel_reason = data.reason
    db.flush()
    _audit(db, user.id, "CANCEL", request, "取消采购申请")
    db.commit()
    return _require_request(db, request.id)
