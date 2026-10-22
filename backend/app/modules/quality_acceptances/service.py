"""质量验收创建、检测结果录入和到货状态更新的业务逻辑。"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.quality_acceptances import crud
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.quality_acceptances.scope import acceptance_read_condition
from app.modules.quality_acceptances.schema import QualityAcceptanceCreate, QualityAcceptanceResult
from app.modules.notifications.service import notify_users
from app.modules.operation_exceptions.service import create_automatic_exception
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _require_acceptance(db: Session, acceptance_id: int, *, for_update: bool = False) -> QualityAcceptance:
    """查询验收记录，不存在时抛出业务异常。"""

    acceptance = crud.get_by_id(db, acceptance_id, for_update=for_update)
    if acceptance is None:
        raise ResourceNotFoundError(f"质量验收记录 {acceptance_id} 不存在")
    return acceptance


def create_acceptance(db: Session, user: User, data: QualityAcceptanceCreate) -> QualityAcceptance:
    """为已收货到货单创建待检验记录。"""

    inspector = db.get(User, data.inspector_id)
    if inspector is None or not _is_inspector(db, inspector):
        raise BusinessValidationError("请选择有效且具有验收办理权限的质量检验员")
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
        inspector_id=inspector.id,
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


def _is_inspector(db: Session, user: User) -> bool:
    return (user.status == "ACTIVE"
            and bool({"QUALITY", "QUALITY_MANAGER"} & set(get_user_role_codes(db, user.id)))
            and {"quality.acceptances.read", "quality.acceptances.write"}
            <= set(get_user_permission_codes(db, user.id)))


def assignment_options(db: Session) -> dict:
    """只向获准指派者提供待送检单号和有效检验员，不开放系统用户目录。"""
    deliveries = db.scalars(select(Delivery).where(Delivery.status == "RECEIVED").order_by(Delivery.id.desc())).all()
    inspectors = [user for user in db.scalars(select(User).where(User.status == "ACTIVE").order_by(User.id))
                  if _is_inspector(db, user)]
    return {"deliveries": deliveries, "inspectors": inspectors}


def list_acceptances(db: Session, user: User, *, result: str | None, page: int, page_size: int):
    """按用户数据范围分页查询质量验收记录。"""

    condition = acceptance_read_condition(user, get_user_role_codes(db, user.id))
    return crud.list_page(db, scope_condition=condition, result=result, page=page, page_size=page_size)


def get_acceptance(db: Session, user: User, acceptance_id: int, *, for_update: bool = False) -> QualityAcceptance:
    """查询验收记录并校验用户数据范围。"""

    acceptance = _require_acceptance(db, acceptance_id, for_update=for_update)
    if db.scalar(select(QualityAcceptance.id).where(
        QualityAcceptance.id == acceptance_id,
        acceptance_read_condition(user, get_user_role_codes(db, user.id)),
    )) is None:
        raise ResourceNotFoundError(f"质量验收记录 {acceptance_id} 不存在")
    return acceptance


def get_acceptance_by_no(db: Session, user: User, acceptance_no: str) -> QualityAcceptance | None:
    """按完整验收编号读取用户可见记录；不存在与不可见统一返回空。"""

    condition = acceptance_read_condition(user, get_user_role_codes(db, user.id))
    return db.scalar(select(QualityAcceptance).where(
        QualityAcceptance.acceptance_no == acceptance_no,
        condition,
    ))


def submit_result(db: Session, user: User, acceptance_id: int, data: QualityAcceptanceResult) -> QualityAcceptance:
    """提交验收结果，并同步更新到货单质量状态。"""

    acceptance = get_acceptance(db, user, acceptance_id, for_update=True)
    if acceptance.result in {"PASSED", "PARTIAL", "FAILED"} and data.result != "REINSPECTION":
        raise BusinessValidationError("已完成的验收只能先发起复检")
    delivery = crud.get_delivery(db, acceptance.delivery_id, for_update=True)
    if delivery is None:
        raise ResourceNotFoundError("关联到货单不存在")
    delivery_item_ids = set(db.scalars(select(DeliveryItem.id).where(DeliveryItem.delivery_id == delivery.id)).all())
    if data.item_results is not None:
        supplied = [item.delivery_item_id for item in data.item_results]
        if len(supplied) != len(set(supplied)) or set(supplied) != delivery_item_ids:
            raise BusinessValidationError("请为当前到货单的每条明细分别填写检测结果，且不能重复")
        if data.test_result is not None:
            raise BusinessValidationError("已按明细填写检测结果时，不可同时提交旧的整单检测结果")
        test_result = {"by_delivery_item": {str(item.delivery_item_id): item.tests for item in data.item_results}}
    else:
        if len(delivery_item_ids) > 1 and data.result != "REINSPECTION":
            raise BusinessValidationError("多明细验收单必须按到货明细分别填写检测结果")
        test_result = data.test_result
    acceptance.result = data.result
    acceptance.test_result = test_result
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
