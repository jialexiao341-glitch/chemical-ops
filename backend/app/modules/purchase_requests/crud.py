"""采购申请模块的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.purchase_requests.model import (
    PurchaseRequest,
    PurchaseRequestApproval,
    PurchaseRequestItem,
)


def get_by_id(db: Session, request_id: int) -> PurchaseRequest | None:
    """按主键查询采购申请及其明细、审批记录。"""

    return db.scalar(
        select(PurchaseRequest)
        .options(selectinload(PurchaseRequest.items), selectinload(PurchaseRequest.approvals))
        .where(PurchaseRequest.id == request_id)
    )


def list_page(
    db: Session,
    *,
    applicant_id: int | None,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[PurchaseRequest], int]:
    """按用户范围和筛选条件返回采购申请分页数据。"""

    conditions = []
    if applicant_id is not None:
        conditions.append(PurchaseRequest.applicant_id == applicant_id)
    if keyword:
        conditions.append(
            PurchaseRequest.request_no.like(f"%{keyword}%")
            | PurchaseRequest.purpose.like(f"%{keyword}%")
        )
    if status:
        conditions.append(PurchaseRequest.status == status)

    total = db.scalar(select(func.count(PurchaseRequest.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(PurchaseRequest)
            .options(selectinload(PurchaseRequest.items), selectinload(PurchaseRequest.approvals))
            .where(*conditions)
            .order_by(PurchaseRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_pending_approval(db: Session, request_id: int) -> PurchaseRequestApproval | None:
    """查询采购申请当前待处理的审批节点。"""

    return db.scalar(
        select(PurchaseRequestApproval)
        .where(
            PurchaseRequestApproval.request_id == request_id,
            PurchaseRequestApproval.action == "PENDING",
        )
        .order_by(PurchaseRequestApproval.sequence_no)
    )


def delete_items(db: Session, request_id: int) -> None:
    """删除申请明细，供草稿整体替换明细时使用。"""

    db.query(PurchaseRequestItem).filter(PurchaseRequestItem.request_id == request_id).delete(
        synchronize_session=False
    )


def delete_approvals(db: Session, request_id: int) -> None:
    """删除旧审批节点，供驳回后重新提交时使用。"""

    db.query(PurchaseRequestApproval).filter(
        PurchaseRequestApproval.request_id == request_id
    ).delete(synchronize_session=False)
