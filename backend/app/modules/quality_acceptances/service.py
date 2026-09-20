"""质量验收创建、检测结果录入和到货状态更新的业务逻辑。"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery
from app.modules.quality_acceptances import crud
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate, QualityAcceptanceResult
from app.modules.notifications.service import notify_users
from app.modules.operation_exceptions.service import create_automatic_exception
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _can_manage_all(db: Session, user: User) -> bool:
    """判断用户是否可以查看全部质量验收记录。"""

    return bool({"SYS_ADMIN", "PROCUREMENT_MANAGER", "QUALITY", "WAREHOUSE"} & set(get_user_role_codes(db, user.id)))


def _require_acceptance(db: Session, acceptance_id: int, *, for_update: bool = False) -> QualityAcceptance:
    """查询验收记录，不存在时抛出业务异常。"""

    acceptance = crud.get_by_id(db, acceptance_id, for_update=for_update)
    if acceptance is None:
        raise ResourceNotFoundError(f"质量验收记录 {acceptance_id} 不存在")
    return acceptance


def create_acceptance(db: Session, user: User, data: QualityAcceptanceCreate) -> QualityAcceptance:
    """为已收货到货单创建待检验记录。"""

    delivery = crud.get_delivery(db, data.delivery_id, for_update=True)
    if delivery is None:
        raise ResourceNotFoundError("到货单不存在")
    if delivery.status != "RECEIVED":
        raise BusinessValidationError("只有已确认收货的到货单可以发起质量验收")
    if crud.get_by_delivery(db, delivery.id) is not None:
        raise BusinessValidationError("该到货单已经存在质量验收记录")
    acceptance = QualityAcceptance(
        acceptance_no=f"TEMP-QA-{user.id}-{int(_now().timestamp())}",
        delivery_id=delivery.id,
        inspector_id=user.id,
        result="PENDING",
        certificate_complete=0,
    )
    db.add(acceptance)
    db.flush()
    acceptance.acceptance_no = f"QA{date.today():%Y%m%d}{acceptance.id:06d}"
    delivery.status = "INSPECTING"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="QUALITY_ACCEPTANCE", resource_id=acceptance.id, request_summary="创建质量验收记录", result_status="SUCCESS")
    db.commit()
    return _require_acceptance(db, acceptance.id)


def list_acceptances(db: Session, user: User, *, result: str | None, page: int, page_size: int):
    """按用户数据范围分页查询质量验收记录。"""

    delivery_ids = None
    if not _can_manage_all(db, user):
        delivery_ids = {
            delivery.id
            for delivery in db.scalars(
                select(Delivery).join(QualityAcceptance, QualityAcceptance.delivery_id == Delivery.id).where(
                    QualityAcceptance.inspector_id == user.id
                )
            ).all()
        }
    return crud.list_page(db, delivery_ids=delivery_ids, result=result, page=page, page_size=page_size)


def get_acceptance(db: Session, user: User, acceptance_id: int, *, for_update: bool = False) -> QualityAcceptance:
    """查询验收记录并校验用户数据范围。"""

    acceptance = _require_acceptance(db, acceptance_id, for_update=for_update)
    if not _can_manage_all(db, user) and acceptance.inspector_id != user.id:
        raise ResourceNotFoundError(f"质量验收记录 {acceptance_id} 不存在")
    return acceptance


def submit_result(db: Session, user: User, acceptance_id: int, data: QualityAcceptanceResult) -> QualityAcceptance:
    """提交验收结果，并同步更新到货单质量状态。"""

    acceptance = get_acceptance(db, user, acceptance_id, for_update=True)
    if acceptance.result in {"PASSED", "PARTIAL", "FAILED"} and data.result != "REINSPECTION":
        raise BusinessValidationError("已完成的验收只能先发起复检")
    delivery = crud.get_delivery(db, acceptance.delivery_id, for_update=True)
    if delivery is None:
        raise ResourceNotFoundError("关联到货单不存在")
    acceptance.result = data.result
    acceptance.test_result = data.test_result
    acceptance.certificate_complete = 1 if data.certificate_complete else 0
    acceptance.report_file_id = data.report_file_id
    acceptance.conclusion = data.conclusion
    acceptance.inspection_time = _now()
    if data.result == "PASSED":
        delivery.status = "ACCEPTED"
    elif data.result == "REINSPECTION":
        delivery.status = "INSPECTING"
    else:
        delivery.status = "EXCEPTION"
    if data.result in {"PARTIAL", "FAILED"}:
        order = db.get(PurchaseOrder, delivery.po_id)
        exception = create_automatic_exception(
            db,
            user,
            exception_type="QUALITY",
            source_type="QUALITY_ACCEPTANCE",
            source_id=acceptance.id,
            po_id=delivery.po_id,
            delivery_id=delivery.id,
            owner_id=order.buyer_id if order is not None else None,
            severity="HIGH" if data.result == "FAILED" else "MEDIUM",
            description=f"质量验收 {acceptance.acceptance_no} 结果为 {data.result}：{data.conclusion or '请处理'}",
        )
        if exception is not None:
            notify_users(
                db,
                recipient_ids=[order.buyer_id] if order is not None else [],
                role_codes=["PROCUREMENT_MANAGER", "QUALITY"],
                notification_type="EXCEPTION_CREATED",
                title="质量验收异常待处理",
                content=exception.description,
                related_type="OPERATION_EXCEPTION",
                related_id=exception.id,
            )
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT_RESULT", resource_type="QUALITY_ACCEPTANCE", resource_id=acceptance.id, request_summary=f"提交质量验收结果 {data.result}", result_status="SUCCESS")
    db.commit()
    return _require_acceptance(db, acceptance.id)
