"""异常登记、指派、处理和关闭的业务逻辑。"""

from datetime import datetime

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.inventory.model import InventoryBalance, InventoryBatch, Warehouse
from app.modules.insights.model import ExceptionActionDecision
from app.modules.operation_exceptions import crud
from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment
from app.modules.operation_exceptions.schema import (
    OperationExceptionCreate,
    OperationExceptionUpdate,
    OperationTaskCommentCreate,
    OperationTaskCreate,
    OperationTaskUpdate,
)
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.products.model import Product
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.file_model import SysFile
from app.modules.system.model import Department, User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _exception_scope_condition(db: Session, user: User):
    """按来源对象读取范围或用户责任部门限制异常记录。"""

    roles = set(get_user_role_codes(db, user.id))
    if "SYS_ADMIN" in roles:
        return True

    scopes = []
    permissions = set(get_user_permission_codes(db, user.id))
    order_scope = order_read_condition(user, roles)
    if "procurement.orders.read" in permissions:
        visible_orders = select(PurchaseOrder.id).where(order_scope)
        scopes.append(and_(
            OperationException.source_type == "PURCHASE_ORDER",
            OperationException.source_id.in_(visible_orders),
        ))
        visible_deliveries = select(Delivery.id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(order_scope)
        scopes.append(and_(
            OperationException.source_type == "DELIVERY",
            OperationException.source_id.in_(visible_deliveries),
        ))
        visible_delivery_items = select(DeliveryItem.id).join(Delivery, Delivery.id == DeliveryItem.delivery_id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(order_scope)
        scopes.append(and_(
            OperationException.source_type == "DELIVERY_ITEM",
            OperationException.source_id.in_(visible_delivery_items),
        ))

    if "quality.acceptances.read" in permissions:
        from app.modules.quality_acceptances.model import QualityAcceptance

        acceptance_scope = True if roles & {"PROCUREMENT_MANAGER", "WAREHOUSE", "QUALITY_MANAGER"} else QualityAcceptance.inspector_id == user.id
        visible_acceptances = select(QualityAcceptance.id).where(acceptance_scope)
        scopes.append(and_(
            OperationException.source_type == "QUALITY_ACCEPTANCE",
            OperationException.source_id.in_(visible_acceptances),
        ))

    if "warehouse.inventory.read" in permissions:
        warehouse_scope = True if roles & {"PROCUREMENT_MANAGER"} else or_(
            Warehouse.manager_id == user.id,
            Warehouse.manager_id.is_(None),
        )
        visible_batches = select(InventoryBalance.batch_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id).where(warehouse_scope)
        scopes.append(and_(
            OperationException.source_type == "INVENTORY_BATCH",
            OperationException.source_id.in_(visible_batches),
        ))
        visible_products = select(InventoryBalance.product_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id).where(warehouse_scope)
        scopes.append(and_(
            OperationException.source_type == "PRODUCT",
            OperationException.source_id.in_(visible_products),
        ))

    if "master.products.read" in permissions:
        scopes.append(and_(
            OperationException.source_type == "PRODUCT",
            OperationException.source_id.in_(select(Product.id).where(Product.status == "ACTIVE")),
        ))
    return or_(*scopes) if scopes else false()


def _exception_record_scope_condition(db: Session, user: User):
    """合并来源/部门、负责人和任务指派范围。"""

    if "SYS_ADMIN" in set(get_user_role_codes(db, user.id)):
        return True
    return or_(
        OperationException.owner_id == user.id,
        exists(select(OperationTask.id).where(
            OperationTask.exception_id == OperationException.id,
            OperationTask.assignee_id == user.id,
        )),
        _exception_scope_condition(db, user),
    )


def _has_exception_scope(db: Session, user: User, exception: OperationException) -> bool:
    return db.scalar(select(OperationException.id).where(
        OperationException.id == exception.id,
        _exception_record_scope_condition(db, user),
    )) is not None


def _has_source_exception_scope(db: Session, user: User, exception: OperationException) -> bool:
    return db.scalar(select(OperationException.id).where(
        OperationException.id == exception.id,
        _exception_scope_condition(db, user),
    )) is not None


def _has_source_scope(db: Session, user: User, data: OperationExceptionCreate) -> bool:
    """验证手工异常引用的来源记录处于当前用户可读范围。"""

    roles = set(get_user_role_codes(db, user.id))
    if "SYS_ADMIN" in roles:
        return True
    permissions = set(get_user_permission_codes(db, user.id))
    order_scope = order_read_condition(user, roles)
    if data.source_type == "PURCHASE_ORDER" and "procurement.orders.read" in permissions:
        return db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.id == data.source_id, order_scope)) is not None
    if data.source_type in {"DELIVERY", "DELIVERY_ITEM"} and "procurement.orders.read" in permissions:
        delivery_id = data.source_id
        if data.source_type == "DELIVERY_ITEM":
            delivery_id = db.scalar(select(DeliveryItem.delivery_id).where(DeliveryItem.id == data.source_id))
        if delivery_id is not None:
            return db.scalar(select(Delivery.id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(Delivery.id == delivery_id, order_scope)) is not None
    if data.source_type == "QUALITY_ACCEPTANCE" and "quality.acceptances.read" in permissions:
        from app.modules.quality_acceptances.model import QualityAcceptance

        acceptance_scope = True if roles & {"PROCUREMENT_MANAGER", "WAREHOUSE", "QUALITY_MANAGER"} else QualityAcceptance.inspector_id == user.id
        return db.scalar(select(QualityAcceptance.id).where(QualityAcceptance.id == data.source_id, acceptance_scope)) is not None
    if data.source_type == "INVENTORY_BATCH" and "warehouse.inventory.read" in permissions:
        warehouse_scope = True if roles & {"PROCUREMENT_MANAGER"} else or_(Warehouse.manager_id == user.id, Warehouse.manager_id.is_(None))
        return db.scalar(select(InventoryBalance.id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id).where(InventoryBalance.batch_id == data.source_id, warehouse_scope).limit(1)) is not None
    if data.source_type == "PRODUCT" and "master.products.read" in permissions:
        return db.scalar(select(Product.id).where(Product.id == data.source_id, Product.status == "ACTIVE")) is not None
    if data.source_type == "OTHER":
        return data.owner_id == user.id
    return False


def _require_exception(db: Session, exception_id: int, *, for_update: bool = False) -> OperationException:
    """查询异常，不存在时抛出业务异常。"""

    exception = crud.get_by_id(db, exception_id, for_update=for_update)
    if exception is None:
        raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    return exception


def _validate_source(db: Session, data: OperationExceptionCreate) -> None:
    """校验异常来源和关联业务 ID。"""

    if data.source_type == "PURCHASE_ORDER" and (db.get(PurchaseOrder, data.source_id) is None or data.po_id != data.source_id):
        raise BusinessValidationError("采购订单异常的 source_id 和 po_id 必须指向同一订单")
    if data.source_type == "DELIVERY" and (db.get(Delivery, data.source_id) is None or data.delivery_id != data.source_id):
        raise BusinessValidationError("到货异常的 source_id 和 delivery_id 必须指向同一到货单")
    if data.source_type == "DELIVERY_ITEM":
        item = db.get(DeliveryItem, data.source_id)
        if item is None or data.delivery_item_id != data.source_id:
            raise BusinessValidationError("到货明细异常的 source_id 和 delivery_item_id 必须指向同一明细")
    if data.source_type == "QUALITY_ACCEPTANCE" and db.get(QualityAcceptance, data.source_id) is None:
        raise BusinessValidationError("质量验收异常的 source_id 必须指向已存在的验收记录")
    if data.source_type == "INVENTORY_BATCH" and db.get(InventoryBatch, data.source_id) is None:
        raise BusinessValidationError("库存批次异常的 source_id 必须指向已存在的库存批次")
    if data.source_type == "PRODUCT" and db.get(Product, data.source_id) is None:
        raise BusinessValidationError("产品异常的 source_id 必须指向已存在的产品")
    if data.source_type == "OTHER" and data.source_id <= 0:
        raise BusinessValidationError("异常来源 ID 无效")
    if data.owner_id is not None:
        owner = db.get(User, data.owner_id)
        if owner is None or owner.status != "ACTIVE":
            raise BusinessValidationError("异常负责人不存在或已停用")
    if data.responsible_department_id is not None:
        department = db.get(Department, data.responsible_department_id)
        if department is None or department.status != "ACTIVE":
            raise BusinessValidationError("责任部门不存在或已停用")


def create_exception(db: Session, user: User, data: OperationExceptionCreate) -> OperationException:
    """登记一条采购运营异常。"""

    if data.source_type == "OTHER":
        if data.responsible_department_id is None:
            data.responsible_department_id = user.department_id
        if data.owner_id is None:
            data.owner_id = user.id
    if not _has_source_scope(db, user, data):
        raise ResourceNotFoundError("异常来源不存在或不在当前用户数据范围内")
    _validate_source(db, data)
    duplicate = db.scalar(select(OperationException).where(OperationException.exception_type == data.exception_type, OperationException.source_type == data.source_type, OperationException.source_id == data.source_id, OperationException.status.in_(("OPEN", "PROCESSING", "RESOLVED"))))
    if duplicate is not None:
        raise DuplicateResourceError("同一来源的未关闭异常已存在")
    exception = OperationException(
        exception_no=f"TEMP-EX-{user.id}-{int(_now().timestamp())}",
        **data.model_dump(),
        status="OPEN",
    )
    db.add(exception)
    db.flush()
    exception.exception_no = f"EX{_now():%Y%m%d}{exception.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="OPERATION_EXCEPTION", resource_id=exception.id, request_summary="登记运营异常", result_status="SUCCESS")
    db.commit()
    return _require_exception(db, exception.id)


def create_automatic_exception(
    db: Session,
    user: User,
    *,
    exception_type: str,
    source_type: str,
    source_id: int,
    description: str,
    severity: str,
    po_id: int | None = None,
    delivery_id: int | None = None,
    delivery_item_id: int | None = None,
    owner_id: int | None = None,
) -> OperationException | None:
    """为业务事件创建异常；已有未关闭同类异常时不重复创建。"""

    source_model = {"DELIVERY": Delivery, "QUALITY_ACCEPTANCE": QualityAcceptance, "INVENTORY_BATCH": InventoryBatch, "PRODUCT": Product}.get(source_type)
    if source_model is not None:
        source = db.scalar(select(source_model).where(source_model.id == source_id).with_for_update())
        if source is None:
            raise ResourceNotFoundError(f"自动异常来源 {source_type}:{source_id} 不存在")

    duplicate_conditions = [
        OperationException.exception_type == exception_type,
        OperationException.source_type == source_type,
        OperationException.source_id == source_id,
    ]
    # 定时库存临期和待验收提醒会重复扫描同一业务事实；关闭后不应每周期重新通知。
    if exception_type not in {"INVENTORY_EXPIRY", "QUALITY_PENDING"}:
        duplicate_conditions.append(OperationException.status.in_(("OPEN", "PROCESSING", "RESOLVED")))
    existing = db.scalar(select(OperationException).where(*duplicate_conditions).with_for_update())
    if existing is not None:
        return None
    exception = OperationException(
        exception_no=f"TMP{source_type[:4]}{source_id}{int(_now().timestamp() * 1000)}",
        exception_type=exception_type,
        source_type=source_type,
        source_id=source_id,
        po_id=po_id,
        delivery_id=delivery_id,
        delivery_item_id=delivery_item_id,
        owner_id=owner_id,
        severity=severity,
        description=description,
        status="OPEN",
    )
    try:
        with db.begin_nested():
            db.add(exception)
            db.flush()
            exception.exception_no = f"EX{_now():%Y%m%d}{exception.id:06d}"
            add_audit_log(db, actor_id=user.id, action_type="AUTO_CREATE", resource_type="OPERATION_EXCEPTION", resource_id=exception.id, request_summary="业务事件自动生成运营异常", result_status="SUCCESS")
    except IntegrityError:
        existing = db.scalar(select(OperationException).where(*duplicate_conditions).order_by(OperationException.id).limit(1))
        if existing is not None:
            return None
        raise
    return exception


def list_exceptions(db: Session, user: User, *, exception_type: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询异常。"""

    scope = _exception_record_scope_condition(db, user)
    return crud.list_page(db, scope_condition=scope, exception_type=exception_type, status=status, page=page, page_size=page_size)


def get_exception(db: Session, user: User, exception_id: int, *, for_update: bool = False) -> OperationException:
    """查询异常并校验负责人数据范围。"""

    exception = _require_exception(db, exception_id, for_update=for_update)
    if not _has_exception_scope(db, user, exception):
        raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    return exception


def update_exception(db: Session, user: User, exception_id: int, data: OperationExceptionUpdate) -> OperationException:
    """指派负责人并推进异常状态。"""

    exception = get_exception(db, user, exception_id, for_update=True)
    if exception.owner_id != user.id and not _has_source_exception_scope(db, user, exception):
        raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    if exception.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的异常不能修改")
    values = data.model_dump(exclude_unset=True)
    if "owner_id" in values and data.owner_id is not None:
        _validate_assignee(db, user, data.owner_id)
    next_status = data.status
    if next_status:
        if next_status in {"RESOLVED", "CLOSED"}:
            decision = db.scalar(select(ExceptionActionDecision).where(ExceptionActionDecision.exception_id == exception.id, ExceptionActionDecision.decision == "ADOPTED"))
            if decision is not None:
                linked_task = db.get(OperationTask, decision.task_id)
                if linked_task is None or linked_task.status != "COMPLETED":
                    raise BusinessValidationError("采纳的处置建议任务尚未完成，不能解决或关闭异常")
        allowed = {
            "OPEN": {"PROCESSING", "CANCELLED"},
            "PROCESSING": {"RESOLVED", "CANCELLED"},
            "RESOLVED": {"CLOSED", "PROCESSING"},
        }
        if next_status not in allowed.get(exception.status, set()):
            raise BusinessValidationError(f"异常不能从 {exception.status} 变更为 {next_status}")
        if next_status == "CLOSED" and not data.closing_note:
            raise BusinessValidationError("关闭异常必须填写关闭说明")
        exception.status = next_status
        if next_status == "CLOSED":
            exception.closed_by = user.id
            exception.closed_at = _now()
    for field in ("owner_id", "due_at", "closing_note"):
        if field in values:
            setattr(exception, field, values[field])
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="OPERATION_EXCEPTION", resource_id=exception.id, request_summary=f"更新异常状态 {exception.status}", result_status="SUCCESS")
    db.commit()
    return _require_exception(db, exception.id)


def close_recovered_low_stock_alert(db: Session, user: User, exception_id: int) -> bool:
    """Close an untouched low-stock alert after its available stock recovers."""

    exception = _require_exception(db, exception_id, for_update=True)
    if (
        exception.exception_type != "LOW_STOCK"
        or exception.source_type != "PRODUCT"
        or exception.status != "OPEN"
    ):
        return False
    has_tasks = db.scalar(select(OperationTask.id).where(OperationTask.exception_id == exception.id).limit(1))
    if has_tasks is not None:
        return False
    update_exception(db, user, exception.id, OperationExceptionUpdate(status="PROCESSING"))
    update_exception(db, user, exception.id, OperationExceptionUpdate(status="RESOLVED"))
    update_exception(
        db,
        user,
        exception.id,
        OperationExceptionUpdate(
            status="CLOSED",
            closing_note="系统自动关闭：可用库存已恢复到安全库存阈值。",
        ),
    )
    return True


def _can_access_task(db: Session, user: User, task: OperationTask) -> bool:
    """判断用户是否可以访问异常任务。"""

    exception = _require_exception(db, task.exception_id)
    return _has_source_exception_scope(db, user, exception) or exception.owner_id == user.id or task.assignee_id == user.id


def _require_task(db: Session, task_id: int, *, for_update: bool = False) -> OperationTask:
    """查询任务，不存在时抛出业务异常。"""

    task = crud.get_task(db, task_id, for_update=for_update)
    if task is None:
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    return task


def _validate_assignee(db: Session, user: User, assignee_id: int | None) -> None:
    """校验异常经办人处于允许的部门范围且启用。"""

    if assignee_id is not None:
        assignee = db.get(User, assignee_id)
        if assignee is None or assignee.status != "ACTIVE":
            raise BusinessValidationError("任务负责人不存在或已停用")
        roles = set(get_user_role_codes(db, user.id))
        if "SYS_ADMIN" not in roles and assignee.department_id != user.department_id:
            raise ResourceNotFoundError("异常经办人不存在或不在当前用户数据范围内")


def list_assignee_options(db: Session, user: User) -> list[User]:
    """返回异常可指派范围内的启用用户，不暴露系统用户目录。"""

    roles = set(get_user_role_codes(db, user.id))
    statement = select(User).where(User.status == "ACTIVE")
    if "SYS_ADMIN" not in roles:
        if user.department_id is None:
            statement = statement.where(User.id == user.id)
        else:
            statement = statement.where(User.department_id == user.department_id)
    return list(db.scalars(statement.order_by(User.id)).all())


def list_tasks(db: Session, user: User, exception_id: int, *, status: str | None, page: int, page_size: int):
    """按异常查询处理任务，并校验用户数据范围。"""

    exception = _require_exception(db, exception_id)
    has_full_exception_scope = _has_source_exception_scope(db, user, exception) or exception.owner_id == user.id
    if not has_full_exception_scope:
        assigned = db.scalar(
            select(OperationTask.id).where(OperationTask.exception_id == exception_id, OperationTask.assignee_id == user.id)
        )
        if assigned is None:
            raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    return crud.list_tasks(
        db,
        exception_id=exception.id,
        assignee_id=None if has_full_exception_scope else user.id,
        status=status,
        page=page,
        page_size=page_size,
    )


def create_task(db: Session, user: User, exception_id: int, data: OperationTaskCreate) -> OperationTask:
    """为异常创建处理任务。"""

    exception = get_exception(db, user, exception_id)
    if exception.owner_id != user.id and not _has_source_exception_scope(db, user, exception):
        raise ResourceNotFoundError(f"异常 {exception_id} 不存在")
    if exception.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的异常不能新增处理任务")
    _validate_assignee(db, user, data.assignee_id)
    task = OperationTask(exception_id=exception.id, **data.model_dump())
    db.add(task)
    if exception.status in {"OPEN", "RESOLVED"}:
        exception.status = "PROCESSING"
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="OPERATION_TASK", resource_id=task.id, request_summary="创建异常处理任务", result_status="SUCCESS")
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, user: User, task_id: int) -> OperationTask:
    """查询任务并校验用户数据范围。"""

    task = _require_task(db, task_id)
    if not _can_access_task(db, user, task):
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    return task


def update_task(db: Session, user: User, task_id: int, data: OperationTaskUpdate) -> OperationTask:
    """更新任务内容、负责人或处理状态。"""

    task = get_task(db, user, task_id)
    values = data.model_dump(exclude_unset=True)
    if task.status == "CANCELLED":
        raise BusinessValidationError("已取消的任务不能修改")
    if "assignee_id" in values:
        _validate_assignee(db, user, data.assignee_id)
    next_status = data.status
    if next_status:
        allowed = {
            "OPEN": {"PROCESSING", "CANCELLED"},
            "PROCESSING": {"COMPLETED", "CANCELLED"},
            "COMPLETED": {"PROCESSING"},
        }
        if next_status not in allowed.get(task.status, set()):
            raise BusinessValidationError(f"任务不能从 {task.status} 变更为 {next_status}")
        if next_status == "COMPLETED" and not (data.completion_note or task.completion_note):
            raise BusinessValidationError("完成任务必须填写完成说明")
        task.status = next_status
        if next_status == "COMPLETED":
            task.completed_at = _now()
        else:
            task.completed_at = None
    for field in ("title", "assignee_id", "priority", "due_at", "completion_note"):
        if field in values:
            setattr(task, field, values[field])
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="OPERATION_TASK", resource_id=task.id, request_summary=f"更新异常任务状态 {task.status}", result_status="SUCCESS")
    db.commit()
    db.refresh(task)
    return task


def list_comments(db: Session, user: User, task_id: int, *, page: int, page_size: int):
    """分页查询任务处理记录。"""

    task = get_task(db, user, task_id)
    return crud.list_comments(db, task_id=task.id, page=page, page_size=page_size)


def create_comment(db: Session, user: User, task_id: int, data: OperationTaskCommentCreate) -> OperationTaskComment:
    """为异常任务追加处理记录。"""

    task = get_task(db, user, task_id)
    if task.status == "CANCELLED":
        raise BusinessValidationError("已取消的任务不能追加处理记录")
    if data.attachment_file_id is not None and db.get(SysFile, data.attachment_file_id) is None:
        raise BusinessValidationError("附件文件不存在")
    comment = OperationTaskComment(task_id=task.id, commenter_id=user.id, **data.model_dump())
    db.add(comment)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="OPERATION_TASK_COMMENT", resource_id=comment.id, request_summary="追加异常任务处理记录", result_status="SUCCESS")
    db.commit()
    db.refresh(comment)
    return comment
