"""供应商门户订单查询和供应商确认逻辑。"""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.core.time import business_today, utc_now
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance import reconciliation_items
from app.modules.finance.model import FinanceReconciliation
from app.modules.files import service as file_service
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderEvent, PurchaseOrderItem
from app.modules.rfqs.model import RFQ, RFQItem, RFQSupplier, SupplierQuote
from app.modules.rfqs.schema import SupplierQuoteCreate, SupplierQuoteItemCreate
from app.modules.rfqs.service import create_quote_for_supplier
from app.modules.suppliers.model import Supplier
from app.modules.supplier_portal.model import (
    SupplierDeliveryUpdate,
    SupplierPortalAccount,
    SupplierQualityDocument,
    SupplierReconciliationMessage,
)
from app.modules.supplier_portal.schema import (
    SupplierPortalQuoteCreate,
    SupplierPortalQuoteItemRead,
    SupplierPortalQuoteRead,
    SupplierDeliveryDateUpdate,
    SupplierDeliveryUpdatePage,
    SupplierDeliveryUpdateRead,
    SupplierQualityDocumentPage,
    SupplierQualityDocumentRead,
    SupplierReconciliationMessageCreate,
    SupplierReconciliationMessagePage,
    SupplierReconciliationMessageRead,
    SupplierReconciliationPage,
    SupplierReconciliationRead,
    SupplierShipmentCreate,
    SupplierShipmentPage,
    SupplierShipmentRead,
    SupplierRFQDetail,
    SupplierRFQItemRead,
    SupplierRFQListItem,
    SupplierRFQPage,
)
from app.modules.system.audit import add_audit_log
from app.modules.system.file_model import SysFile, SysFileAttachment
from app.modules.system.model import User
from app.modules.system import crud as system_crud


def _supplier_id(db: Session, user: User) -> int:
    """读取当前登录用户绑定的供应商，并校验供应商处于启用状态。"""
    if set(system_crud.get_user_role_codes(db, user.id)) != {"SUPPLIER_PORTAL"}:
        raise AuthorizationError("仅供应商门户角色账号可访问供应商业务")
    account = db.scalar(
        select(SupplierPortalAccount)
        .join(Supplier, Supplier.id == SupplierPortalAccount.supplier_id)
        .where(
            SupplierPortalAccount.user_id == user.id,
            SupplierPortalAccount.status == "ACTIVE",
            Supplier.status == "ACTIVE",
        )
    )
    if account is None:
        raise AuthorizationError("当前用户未绑定有效的供应商门户账号")
    return account.supplier_id


def _invited_rfq(db: Session, supplier_id: int, rfq_id: int, *, for_update: bool = False) -> tuple[RFQ, RFQSupplier]:
    """只按当前绑定供应商的邀请关系查询询价。"""
    row = db.execute(
        select(RFQ, RFQSupplier)
        .join(RFQSupplier, RFQSupplier.rfq_id == RFQ.id)
        .options(selectinload(RFQ.items))
        .where(
            RFQ.id == rfq_id,
            RFQSupplier.supplier_id == supplier_id,
            RFQ.status != "DRAFT",
        )
    ).first()
    if row is None:
        raise ResourceNotFoundError(f"询价单 {rfq_id} 不存在")
    rfq = row[0]
    if for_update:
        rfq = db.scalar(select(RFQ).where(RFQ.id == rfq_id).with_for_update().execution_options(populate_existing=True))
        if rfq is None or rfq.status == "DRAFT":
            raise ResourceNotFoundError(f"询价单 {rfq_id} 不存在")
    return rfq, row[1]


def _rfq_list_item(rfq: RFQ, invitation: RFQSupplier) -> SupplierRFQListItem:
    return SupplierRFQListItem(
        id=rfq.id,
        rfq_no=rfq.rfq_no,
        item_count=len(rfq.items),
        item_summary="、".join(item.requested_name for item in rfq.items[:2])
        + (f"等 {len(rfq.items)} 项" if len(rfq.items) > 2 else ""),
        quote_deadline=rfq.quote_deadline,
        requested_delivery_date=rfq.requested_delivery_date,
        delivery_requirements=rfq.delivery_requirements,
        status=rfq.status,
        response_status=invitation.response_status,
        invited_at=invitation.invited_at,
        response_at=invitation.response_at,
    )


def list_rfqs(
    db: Session,
    user: User,
    *,
    status: str | None,
    page: int,
    page_size: int,
    keyword: str | None = None,
) -> SupplierRFQPage:
    """分页查询邀请当前供应商参与的非草稿询价。"""
    supplier_id = _supplier_id(db, user)
    conditions = [RFQSupplier.supplier_id == supplier_id, RFQ.status != "DRAFT"]
    if status:
        conditions.append(RFQ.status == status)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append((RFQ.rfq_no.like(pattern)) | RFQ.items.any(RFQItem.requested_name.like(pattern)))
    total = db.scalar(
        select(func.count(RFQ.id))
        .join(RFQSupplier, RFQSupplier.rfq_id == RFQ.id)
        .where(*conditions)
    ) or 0
    rows = db.execute(
        select(RFQ, RFQSupplier)
        .join(RFQSupplier, RFQSupplier.rfq_id == RFQ.id)
        .options(selectinload(RFQ.items))
        .where(*conditions)
        .order_by(RFQ.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SupplierRFQPage(
        items=[_rfq_list_item(rfq, invitation) for rfq, invitation in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_rfq(db: Session, user: User, rfq_id: int) -> SupplierRFQDetail:
    """读取邀请当前供应商的询价及其自身最近一版报价。"""
    supplier_id = _supplier_id(db, user)
    rfq, invitation = _invited_rfq(db, supplier_id, rfq_id)
    latest_quote = db.scalar(
        select(SupplierQuote)
        .options(selectinload(SupplierQuote.items))
        .where(SupplierQuote.rfq_id == rfq.id, SupplierQuote.supplier_id == supplier_id)
        .order_by(SupplierQuote.quote_version.desc())
        .limit(1)
    )
    quote = None
    if latest_quote is not None:
        quote = SupplierPortalQuoteRead(
            quote_no=latest_quote.quote_no,
            quote_version=latest_quote.quote_version,
            quote_date=latest_quote.quote_date,
            valid_until=latest_quote.valid_until,
            currency_code=latest_quote.currency_code,
            status=latest_quote.status,
            note=latest_quote.note,
            created_at=latest_quote.created_at,
            items=[
                SupplierPortalQuoteItemRead.model_validate(item)
                for item in latest_quote.items
            ],
        )
    return SupplierRFQDetail(
        **_rfq_list_item(rfq, invitation).model_dump(),
        items=[SupplierRFQItemRead.model_validate(item) for item in rfq.items],
        latest_quote=quote,
    )


def submit_rfq_quote(
    db: Session,
    user: User,
    rfq_id: int,
    data: SupplierPortalQuoteCreate,
) -> SupplierRFQDetail:
    """提交或修订供应商自己的报价版本。"""
    supplier_id = _supplier_id(db, user)
    rfq, _ = _invited_rfq(db, supplier_id, rfq_id, for_update=True)
    if rfq.status not in {"SENT", "RESPONDING"}:
        raise BusinessValidationError("当前询价单已关闭，不接受报价")
    if rfq.quote_deadline is not None and rfq.quote_deadline < datetime.now():
        raise BusinessValidationError("已超过询价报价截止时间")
    if data.valid_until is not None and data.valid_until < business_today():
        raise BusinessValidationError("报价有效期不能早于今天")

    quote_data = SupplierQuoteCreate(
        supplier_id=supplier_id,
        quote_date=data.quote_date,
        valid_until=data.valid_until,
        currency_code=data.currency_code,
        note=data.note,
        items=[
            SupplierQuoteItemCreate.model_validate(item.model_dump())
            for item in data.items
        ],
    )
    create_quote_for_supplier(db, user, rfq, supplier_id, quote_data)
    return get_rfq(db, user, rfq_id)


def _require_order(db: Session, user: User, order_id: int, *, for_update: bool = False) -> PurchaseOrder:
    """查询供应商自己的采购订单，锁定模式下同时锁定订单子表明细与事件。"""
    supplier_id = _supplier_id(db, user)
    statement = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.approvals), selectinload(PurchaseOrder.events))
        .where(PurchaseOrder.id == order_id, PurchaseOrder.supplier_id == supplier_id)
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    order = db.scalar(statement)
    if order is None:
        raise ResourceNotFoundError(f"采购订单 {order_id} 不存在")
    if for_update:
        items = list(
            db.scalars(
                select(PurchaseOrderItem)
                .where(PurchaseOrderItem.po_id == order.id)
                .order_by(PurchaseOrderItem.line_no, PurchaseOrderItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        set_committed_value(order, "items", items)
        events = list(
            db.scalars(
                select(PurchaseOrderEvent)
                .where(PurchaseOrderEvent.po_id == order.id)
                .order_by(PurchaseOrderEvent.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        set_committed_value(order, "events", events)
    return order


def list_orders(db: Session, user: User, *, status: str | None, page: int, page_size: int, keyword: str | None = None):
    """分页查询当前供应商的非草稿订单。"""
    supplier_id = _supplier_id(db, user)
    conditions = [PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status != "DRAFT"]
    if status == "ACTIVE":
        conditions.append(PurchaseOrder.status.in_({"ORDERED", "PARTIAL"}))
    elif status:
        conditions.append(PurchaseOrder.status == status)
    if keyword and keyword.strip():
        conditions.append(PurchaseOrder.po_no.like(f"%{keyword.strip()}%"))
    total = db.scalar(select(func.count(PurchaseOrder.id)).where(*conditions)) or 0
    items = list(db.scalars(select(PurchaseOrder).options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.approvals), selectinload(PurchaseOrder.events)).where(*conditions).order_by(PurchaseOrder.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """查询供应商自己的订单详情。"""
    return _require_order(db, user, order_id)


def confirm_order(db: Session, user: User, order_id: int) -> PurchaseOrder:
    """供应商确认已正式下单的采购订单。"""
    order = _require_order(db, user, order_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL", "COMPLETED"}:
        raise BusinessValidationError("只有已正式下单的采购订单可以由供应商确认")
    if order.supplier_confirmed_at is not None:
        raise BusinessValidationError("该采购订单已经完成供应商确认")
    if any(event.event_type == "SUPPLIER_REJECTED" for event in order.events):
        raise BusinessValidationError("该采购订单已由供应商拒绝，请联系采购处理")
    order.supplier_confirmed_at = datetime.now(timezone.utc)
    order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type="SUPPLIER_CONFIRMED", from_status=order.status, to_status=order.status, event_note="供应商确认采购订单"))
    add_audit_log(db, actor_id=user.id, action_type="CONFIRM", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="供应商确认采购订单", result_status="SUCCESS")
    db.commit()
    return _require_order(db, user, order.id)


def reject_order(db: Session, user: User, order_id: int, reason: str) -> PurchaseOrder:
    """供应商拒绝采购订单并保留订单事件。"""
    order = _require_order(db, user, order_id, for_update=True)
    if order.status != "ORDERED":
        raise BusinessValidationError("只有已下单且尚未收货的采购订单可以由供应商拒绝")
    if order.supplier_confirmed_at is not None:
        raise BusinessValidationError("已确认的采购订单不能再拒绝")
    if any(event.event_type == "SUPPLIER_REJECTED" for event in order.events):
        raise BusinessValidationError("该采购订单已经提交过拒绝记录")
    if db.scalar(select(Delivery.id).where(Delivery.po_id == order.id).limit(1)) is not None:
        raise BusinessValidationError("已存在发货或到货记录的采购订单不能直接拒绝")
    order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type="SUPPLIER_REJECTED", from_status=order.status, to_status=order.status, event_note=reason))
    add_audit_log(db, actor_id=user.id, action_type="REJECT", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary=f"供应商拒绝采购订单：{reason}", result_status="SUCCESS")
    db.commit()
    return _require_order(db, user, order.id)


def update_expected_delivery(db: Session, user: User, order_id: int, data: SupplierDeliveryDateUpdate, *, commit: bool = True):
    """更新当前供应商订单交期并保留历史和订单事件。"""
    order = _require_order(db, user, order_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL"}:
        raise BusinessValidationError("只有已下单或部分到货的订单可以更新预计交期")
    if data.expected_date < business_today():
        raise BusinessValidationError("预计交期不能早于今天")
    previous = order.expected_arrival_date
    order.expected_arrival_date = data.expected_date
    for item in order.items:
        if item.received_quantity < item.order_quantity:
            item.planned_arrival_date = data.expected_date
    update = SupplierDeliveryUpdate(
        po_id=order.id,
        supplier_id=order.supplier_id,
        previous_date=previous,
        expected_date=data.expected_date,
        note=data.note,
        submitted_by=user.id,
        submitted_at=utc_now(),
    )
    db.add(update)
    db.flush()
    order.events.append(PurchaseOrderEvent(
        operator_id=user.id,
        event_type="SUPPLIER_ETA_UPDATE",
        from_status=order.status,
        to_status=order.status,
        event_note=f"供应商更新预计交期：{previous or '未设置'} → {data.expected_date}" + (f"；{data.note}" if data.note else ""),
    ))
    add_audit_log(db, actor_id=user.id, action_type="UPDATE_ETA", resource_type="PURCHASE_ORDER", resource_id=order.id, request_summary="供应商更新预计交期", result_status="SUCCESS")
    if commit:
        db.commit()
    else:
        db.flush()
    return SupplierDeliveryUpdateRead(id=update.id, po_id=order.id, po_no=order.po_no, previous_date=previous, expected_date=data.expected_date, note=data.note, submitted_at=update.submitted_at)


def list_delivery_updates(db: Session, user: User, *, keyword: str | None, page: int, page_size: int):
    supplier_id = _supplier_id(db, user)
    statement = select(SupplierDeliveryUpdate, PurchaseOrder.po_no).join(PurchaseOrder, PurchaseOrder.id == SupplierDeliveryUpdate.po_id).where(SupplierDeliveryUpdate.supplier_id == supplier_id)
    if keyword:
        statement = statement.where(PurchaseOrder.po_no.like(f"%{keyword.strip()}%"))
    total = db.scalar(select(func.count(SupplierDeliveryUpdate.id)).join(PurchaseOrder, PurchaseOrder.id == SupplierDeliveryUpdate.po_id).where(SupplierDeliveryUpdate.supplier_id == supplier_id, *([PurchaseOrder.po_no.like(f"%{keyword.strip()}%") ] if keyword else []))) or 0
    rows = db.execute(statement.order_by(SupplierDeliveryUpdate.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [SupplierDeliveryUpdateRead(id=row.id, po_id=row.po_id, po_no=po_no, previous_date=row.previous_date, expected_date=row.expected_date, note=row.note, submitted_at=row.submitted_at) for row, po_no in rows]
    return SupplierDeliveryUpdatePage(items=items, total=total, page=page, page_size=page_size)


def create_shipment_notice(db: Session, user: User, data: SupplierShipmentCreate):
    """供应商登记发货通知，复用现有到货单和仓库收货流程。"""
    order = _require_order(db, user, data.po_id, for_update=True)
    if order.status not in {"ORDERED", "PARTIAL"}:
        raise BusinessValidationError("只有已下单或部分到货的订单可以提交发货通知")
    if any(event.event_type == "SUPPLIER_REJECTED" for event in order.events):
        raise BusinessValidationError("已拒绝的采购订单不能提交发货通知")
    po_items = {item.id: item for item in order.items}
    item_ids = [item.po_item_id for item in data.items]
    if len(item_ids) != len(set(item_ids)) or not set(item_ids).issubset(po_items):
        raise BusinessValidationError("发货明细必须来自当前订单且不能重复")
    outstanding = {item_id: Decimal(0) for item_id in item_ids}
    existing_items = list(
        db.scalars(
            select(DeliveryItem)
            .join(Delivery, Delivery.id == DeliveryItem.delivery_id)
            .where(Delivery.po_id == order.id, Delivery.status == "IN_TRANSIT", DeliveryItem.po_item_id.in_(item_ids))
            .order_by(DeliveryItem.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    for existing in existing_items:
        outstanding[existing.po_item_id] += Decimal(str(existing.planned_quantity or 0))
    for item in data.items:
        po_item = po_items[item.po_item_id]
        remaining = po_item.order_quantity - po_item.received_quantity - outstanding[item.po_item_id]
        if Decimal(item.planned_quantity) > remaining:
            raise BusinessValidationError(f"订单明细 {po_item.line_no} 剩余可发数量不足")
        if item.production_date and item.expiry_date and item.production_date > item.expiry_date:
            raise BusinessValidationError("生产日期不能晚于有效期")
    delivery = Delivery(
        delivery_no=f"TEMP-D-{uuid4().hex[:12]}",
        po_id=order.id,
        supplier_id=order.supplier_id,
        shipment_date=data.shipment_date,
        expected_arrival_date=data.expected_arrival_date,
        logistics_company=data.logistics_company,
        tracking_no=data.tracking_no,
        status="IN_TRANSIT",
        note=data.note,
    )
    delivery.items = [
        DeliveryItem(
            line_no=index,
            product_id=po_items[item.po_item_id].product_id,
            po_item_id=item.po_item_id,
            batch_no=item.batch_no,
            package_spec=item.package_spec,
            planned_quantity=item.planned_quantity,
            actual_quantity=0,
            short_quantity=0,
            unit_id=po_items[item.po_item_id].unit_id,
            production_date=item.production_date,
            expiry_date=item.expiry_date,
            document_complete=0,
            note=item.note,
        )
        for index, item in enumerate(data.items, start=1)
    ]
    db.add(delivery)
    db.flush()
    delivery.delivery_no = f"DL{date.today():%Y%m%d}{delivery.id:06d}"
    order.events.append(PurchaseOrderEvent(operator_id=user.id, event_type="SUPPLIER_SHIPMENT_NOTICE", from_status=order.status, to_status=order.status, event_note=f"供应商提交发货通知 {delivery.delivery_no}"))
    add_audit_log(db, actor_id=user.id, action_type="SHIPMENT_NOTICE", resource_type="DELIVERY", resource_id=delivery.id, request_summary="供应商提交发货通知", result_status="SUCCESS")
    db.commit()
    return _shipment_read(db, delivery.id)


def _shipment_read(db: Session, delivery_id: int) -> SupplierShipmentRead:
    delivery = db.scalar(select(Delivery).options(selectinload(Delivery.items)).where(Delivery.id == delivery_id))
    order = db.get(PurchaseOrder, delivery.po_id)
    return _shipment_row(delivery, order.po_no)


def _shipment_row(delivery: Delivery, po_no: str) -> SupplierShipmentRead:
    return SupplierShipmentRead(
        id=delivery.id, delivery_no=delivery.delivery_no, po_id=delivery.po_id, po_no=po_no,
        shipment_date=delivery.shipment_date, expected_arrival_date=delivery.expected_arrival_date,
        logistics_company=delivery.logistics_company, tracking_no=delivery.tracking_no,
        status=delivery.status, note=delivery.note, created_at=delivery.created_at, items=delivery.items,
    )


def list_shipment_notices(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    supplier_id = _supplier_id(db, user)
    conditions = [Delivery.supplier_id == supplier_id]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append((Delivery.delivery_no.like(pattern)) | (Delivery.tracking_no.like(pattern)) | (PurchaseOrder.po_no.like(pattern)))
    if status:
        conditions.append(Delivery.status == status)
    total = db.scalar(select(func.count(Delivery.id)).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(*conditions)) or 0
    rows = db.execute(
        select(Delivery, PurchaseOrder.po_no).options(selectinload(Delivery.items))
        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(*conditions)
        .order_by(Delivery.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return SupplierShipmentPage(items=[_shipment_row(delivery, po_no) for delivery, po_no in rows], total=total, page=page, page_size=page_size)


def create_quality_document(db: Session, user: User, *, po_id: int, po_item_id: int | None, document_type: str, note: str | None, file_name: str, mime_type: str, content: bytes, scan_result=None):
    """校验供应商订单后上传并提交质量文件。"""
    order = _require_order(db, user, po_id)
    if po_item_id is not None and po_item_id not in {item.id for item in order.items}:
        raise ResourceNotFoundError("质量资料关联的订单明细不存在")
    if document_type not in {"COA", "SDS", "INSPECTION_REPORT", "OTHER"}:
        raise BusinessValidationError("质量资料类型不正确")
    file_value = file_service.upload_file(db, user, file_name=file_name, mime_type=mime_type, content=content, file_category="QUALITY_REPORT", access_level="INTERNAL", scan_result=scan_result)
    record = SupplierQualityDocument(
        document_no=f"TEMP-SQD-{uuid4().hex[:12]}", supplier_id=order.supplier_id, po_id=order.id,
        po_item_id=po_item_id, file_id=file_value.id, document_type=document_type, status="SUBMITTED",
        note=note, submitted_by=user.id,
    )
    db.add(record)
    db.flush()
    record.document_no = f"SQD{date.today():%Y%m%d}{record.id:06d}"
    db.add(SysFileAttachment(file_id=file_value.id, resource_type="SUPPLIER_QUALITY_DOCUMENT", resource_id=record.id, created_by=user.id))
    db.add(SysFileAttachment(file_id=file_value.id, resource_type="PURCHASE_ORDER", resource_id=order.id, created_by=user.id))
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT_QUALITY_DOC", resource_type="SUPPLIER_QUALITY_DOCUMENT", resource_id=record.id, request_summary=f"供应商提交质量资料 {file_value.file_name}", result_status="SUCCESS")
    db.commit()
    return _quality_document_read(db, record.id)


def _quality_document_read(db: Session, document_id: int) -> SupplierQualityDocumentRead:
    row = db.execute(select(SupplierQualityDocument, PurchaseOrder.po_no, SysFile.file_name).join(PurchaseOrder, PurchaseOrder.id == SupplierQualityDocument.po_id).join(SysFile, SysFile.id == SupplierQualityDocument.file_id).where(SupplierQualityDocument.id == document_id)).first()
    return _quality_document_row(*row)


def _quality_document_row(document: SupplierQualityDocument, po_no: str, file_name: str) -> SupplierQualityDocumentRead:
    return SupplierQualityDocumentRead(id=document.id, document_no=document.document_no, po_id=document.po_id, po_no=po_no, po_item_id=document.po_item_id, file_id=document.file_id, file_name=file_name, document_type=document.document_type, status=document.status, note=document.note, submitted_at=document.submitted_at, review_note=document.review_note)


def list_quality_documents(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    supplier_id = _supplier_id(db, user)
    conditions = [SupplierQualityDocument.supplier_id == supplier_id]
    if status:
        conditions.append(SupplierQualityDocument.status == status)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        conditions.append((SupplierQualityDocument.document_no.like(pattern)) | (PurchaseOrder.po_no.like(pattern)) | (SysFile.file_name.like(pattern)))
    total = db.scalar(select(func.count(SupplierQualityDocument.id)).join(PurchaseOrder, PurchaseOrder.id == SupplierQualityDocument.po_id).join(SysFile, SysFile.id == SupplierQualityDocument.file_id).where(*conditions)) or 0
    rows = db.execute(select(SupplierQualityDocument, PurchaseOrder.po_no, SysFile.file_name).join(PurchaseOrder, PurchaseOrder.id == SupplierQualityDocument.po_id).join(SysFile, SysFile.id == SupplierQualityDocument.file_id).where(*conditions).order_by(SupplierQualityDocument.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return SupplierQualityDocumentPage(items=[_quality_document_row(*row) for row in rows], total=total, page=page, page_size=page_size)


def get_quality_document_file(db: Session, user: User, document_id: int):
    supplier_id = _supplier_id(db, user)
    document = db.scalar(select(SupplierQualityDocument).where(SupplierQualityDocument.id == document_id, SupplierQualityDocument.supplier_id == supplier_id))
    if document is None:
        raise ResourceNotFoundError("质量资料不存在")
    return file_service.read_file(db, user, document.file_id)


def _require_supplier_reconciliation(db: Session, user: User, reconciliation_id: int, *, for_update: bool = False):
    supplier_id = _supplier_id(db, user)
    statement = select(FinanceReconciliation).where(FinanceReconciliation.id == reconciliation_id, FinanceReconciliation.supplier_id == supplier_id)
    if for_update:
        statement = statement.with_for_update()
    value = db.scalar(statement)
    if value is None:
        raise ResourceNotFoundError("对账单不存在")
    return value, supplier_id


def list_supplier_reconciliations(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    supplier_id = _supplier_id(db, user)
    conditions = [FinanceReconciliation.supplier_id == supplier_id]
    if status:
        conditions.append(FinanceReconciliation.status == status)
    if keyword:
        conditions.append((FinanceReconciliation.reconciliation_no.like(f"%{keyword.strip()}%")) | (PurchaseOrder.po_no.like(f"%{keyword.strip()}%")))
    total = db.scalar(select(func.count(FinanceReconciliation.id)).join(PurchaseOrder, PurchaseOrder.id == FinanceReconciliation.po_id).where(*conditions)) or 0
    rows = db.execute(select(FinanceReconciliation, PurchaseOrder.po_no).join(PurchaseOrder, PurchaseOrder.id == FinanceReconciliation.po_id).where(*conditions).order_by(FinanceReconciliation.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [SupplierReconciliationRead(id=rec.id, reconciliation_no=rec.reconciliation_no, po_id=rec.po_id, po_no=po_no, currency_code=rec.currency_code, total_amount=rec.total_amount, status=rec.status, items_version=rec.items_version, note=rec.note, created_at=rec.created_at, updated_at=rec.updated_at) for rec, po_no in rows]
    return SupplierReconciliationPage(items=items, total=total, page=page, page_size=page_size)


def list_reconciliation_messages(db: Session, user: User, reconciliation_id: int, *, page: int = 1, page_size: int = 100):
    reconciliation, supplier_id = _require_supplier_reconciliation(db, user, reconciliation_id)
    total = db.scalar(select(func.count(SupplierReconciliationMessage.id)).where(SupplierReconciliationMessage.reconciliation_id == reconciliation.id)) or 0
    rows = db.scalars(select(SupplierReconciliationMessage).where(SupplierReconciliationMessage.reconciliation_id == reconciliation.id).order_by(SupplierReconciliationMessage.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return SupplierReconciliationMessagePage(items=[SupplierReconciliationMessageRead(id=row.id, author_type=row.author_type, message=row.message, created_at=row.created_at) for row in reversed(rows)], total=total, page=page, page_size=page_size)


def add_supplier_reconciliation_message(db: Session, user: User, reconciliation_id: int, data: SupplierReconciliationMessageCreate):
    reconciliation, supplier_id = _require_supplier_reconciliation(db, user, reconciliation_id, for_update=True)
    if reconciliation.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的对账单不能继续留言")
    row = SupplierReconciliationMessage(reconciliation_id=reconciliation.id, supplier_id=supplier_id, author_id=user.id, author_type="SUPPLIER", message=data.message.strip())
    db.add(row)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="RECONCILIATION_MESSAGE", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="供应商提交对账协同留言", result_status="SUCCESS")
    db.commit()
    return SupplierReconciliationMessageRead(id=row.id, author_type=row.author_type, message=row.message, created_at=row.created_at)


def supplier_confirm_reconciliation(db: Session, user: User, reconciliation_id: int, reason: str | None = None):
    reconciliation, _ = _require_supplier_reconciliation(db, user, reconciliation_id, for_update=True)
    if reconciliation.status not in {"DRAFT", "DISPUTED"}:
        raise BusinessValidationError("当前对账状态不能由供应商确认")
    if reconciliation.items_version < 1:
        raise BusinessValidationError("对账明细尚未生成，不能确认")
    order = _require_order(db, user, reconciliation.po_id, for_update=True)
    from app.modules.finance.service import _check_order_ready_for_reconciliation
    _check_order_ready_for_reconciliation(db, order)
    reconciliation_items.validate_for_confirmation(db, reconciliation, order)
    reconciliation.status = "CONFIRMED"
    reconciliation.confirmed_by = user.id
    reconciliation.confirmed_at = datetime.now(timezone.utc)
    if reason:
        reconciliation.note = reason
    row = SupplierReconciliationMessage(reconciliation_id=reconciliation.id, supplier_id=reconciliation.supplier_id, author_id=user.id, author_type="SUPPLIER", message=reason or "供应商确认对账金额及明细。")
    db.add(row)
    add_audit_log(db, actor_id=user.id, action_type="SUPPLIER_CONFIRM", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="供应商确认对账", result_status="SUCCESS")
    db.commit()
    return reconciliation


def supplier_dispute_reconciliation(db: Session, user: User, reconciliation_id: int, reason: str):
    reconciliation, _ = _require_supplier_reconciliation(db, user, reconciliation_id, for_update=True)
    if reconciliation.status not in {"DRAFT", "CONFIRMED"}:
        raise BusinessValidationError("当前对账状态不能发起争议")
    reconciliation.status = "DISPUTED"
    reconciliation.note = reason
    db.add(SupplierReconciliationMessage(reconciliation_id=reconciliation.id, supplier_id=reconciliation.supplier_id, author_id=user.id, author_type="SUPPLIER", message=reason))
    add_audit_log(db, actor_id=user.id, action_type="SUPPLIER_DISPUTE", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="供应商发起对账争议", result_status="SUCCESS")
    db.commit()
    return reconciliation


def finance_list_reconciliation_messages(db: Session, user: User, reconciliation_id: int, *, page: int = 1, page_size: int = 100):
    from app.modules.finance.service import get_reconciliation
    reconciliation = get_reconciliation(db, user, reconciliation_id)
    total = db.scalar(select(func.count(SupplierReconciliationMessage.id)).where(SupplierReconciliationMessage.reconciliation_id == reconciliation.id)) or 0
    rows = db.scalars(select(SupplierReconciliationMessage).where(SupplierReconciliationMessage.reconciliation_id == reconciliation.id).order_by(SupplierReconciliationMessage.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return SupplierReconciliationMessagePage(items=[SupplierReconciliationMessageRead(id=row.id, author_type=row.author_type, message=row.message, created_at=row.created_at) for row in reversed(rows)], total=total, page=page, page_size=page_size)


def finance_add_reconciliation_message(db: Session, user: User, reconciliation_id: int, data: SupplierReconciliationMessageCreate):
    from app.modules.finance.service import get_reconciliation
    reconciliation = get_reconciliation(db, user, reconciliation_id)
    if reconciliation.status in {"CLOSED", "CANCELLED"}:
        raise BusinessValidationError("已关闭或已取消的对账单不能继续留言")
    row = SupplierReconciliationMessage(reconciliation_id=reconciliation.id, supplier_id=reconciliation.supplier_id, author_id=user.id, author_type="BUYER", message=data.message.strip())
    db.add(row)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="RECONCILIATION_MESSAGE", resource_type="FINANCE_RECONCILIATION", resource_id=reconciliation.id, request_summary="采购方提交对账协同留言", result_status="SUCCESS")
    db.commit()
    return SupplierReconciliationMessageRead(id=row.id, author_type=row.author_type, message=row.message, created_at=row.created_at)
