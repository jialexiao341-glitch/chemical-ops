"""供应商门户订单 HTTP 接口。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.supplier_portal import service
from app.modules.purchase_orders import followup_service
from app.modules.purchase_orders.followup_schema import FollowupPage, FollowupRead, FollowupReply
from app.modules.supplier_portal.schema import (
    SupplierPortalQuoteCreate,
    SupplierRFQDetail,
    SupplierRFQPage,
    SupplierOrderPage,
    SupplierOrderRead,
    SupplierOrderReject,
    SupplierDeliveryDateUpdate,
    SupplierDeliveryUpdatePage,
    SupplierReconciliationAction,
    SupplierReconciliationMessageCreate,
    SupplierReconciliationMessagePage,
    SupplierReconciliationMessageRead,
    SupplierReconciliationPage,
    SupplierShipmentCreate,
    SupplierShipmentPage,
    SupplierShipmentRead,
    SupplierQualityDocumentPage,
    SupplierQualityDocumentRead,
)
from app.modules.files import service as file_service
from app.modules.system.model import User


router = APIRouter(prefix="/supplier-portal/orders", tags=["供应商门户"])
rfqs_router = APIRouter(prefix="/supplier-portal/rfqs", tags=["供应商门户询价"])
collaboration_router = APIRouter(prefix="/supplier-portal", tags=["供应商履约协同"])


@collaboration_router.get('/delivery-followups/{followup_id}', response_model=FollowupRead, summary='读取本供应商催办及订单引用')
def resolve_followup(followup_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission('supplier.portal.delivery.read'))):
    return followup_service.resolve_followup(db, user, followup_id, supplier=True)


@router.get('/{order_id}/followups', response_model=FollowupPage, summary='查询本供应商订单催办')
def list_followups(order_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   db: Session = Depends(get_db), user: User = Depends(require_permission('supplier.portal.delivery.read'))):
    return followup_service.list_followups(db, user, order_id, supplier=True, page=page, page_size=page_size)


@router.post('/{order_id}/followups/{followup_id}/reply', response_model=FollowupRead, summary='回复本供应商交期催办')
def reply_followup(order_id: int, followup_id: int, data: FollowupReply, db: Session = Depends(get_db),
                   user: User = Depends(require_permission('supplier.portal.delivery.update'))):
    return followup_service.reply_followup(db, user, order_id, followup_id, data)


@rfqs_router.get("", response_model=SupplierRFQPage, summary="查询邀请本供应商的询价")
def list_rfqs(
    rfq_status: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("supplier.portal.rfq.read")),
) -> SupplierRFQPage:
    return service.list_rfqs(db, user, status=rfq_status, keyword=keyword, page=page, page_size=page_size)


@rfqs_router.get("/{rfq_id}", response_model=SupplierRFQDetail, summary="查询供应商询价详情")
def get_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("supplier.portal.rfq.read")),
) -> SupplierRFQDetail:
    return service.get_rfq(db, user, rfq_id)


@rfqs_router.post("/{rfq_id}/quotes", response_model=SupplierRFQDetail, summary="提交或修订供应商报价")
def submit_quote(
    rfq_id: int,
    data: SupplierPortalQuoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("supplier.portal.rfq.quote")),
) -> SupplierRFQDetail:
    return service.submit_rfq_quote(db, user, rfq_id, data)


@router.get("", response_model=SupplierOrderPage, summary="查询供应商采购订单")
def list_orders(order_status: str | None = Query(default=None, alias="status"), keyword: str | None = Query(default=None, max_length=100), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.read"))) -> SupplierOrderPage:
    """只返回当前供应商账号绑定供应商的非草稿采购订单。"""
    items, total = service.list_orders(db, user, status=order_status, keyword=keyword, page=page, page_size=page_size)
    return SupplierOrderPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=SupplierOrderRead, summary="查询供应商采购订单详情")
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.read"))) -> SupplierOrderRead:
    """查询当前供应商自己的采购订单。"""
    return service.get_order(db, user, order_id)


@router.post("/{order_id}/confirm", response_model=SupplierOrderRead, summary="供应商确认采购订单")
def confirm_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.confirm"))) -> SupplierOrderRead:
    """供应商确认正式下单的采购订单。"""
    return service.confirm_order(db, user, order_id)


@router.post("/{order_id}/reject", response_model=SupplierOrderRead, summary="供应商拒绝采购订单")
def reject_order(order_id: int, data: SupplierOrderReject, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.confirm"))) -> SupplierOrderRead:
    """供应商拒绝订单并保存原因。"""
    return service.reject_order(db, user, order_id, data.reason)


@collaboration_router.get("/delivery-updates", response_model=SupplierDeliveryUpdatePage, summary="查询供应商交期更新记录")
def list_delivery_updates(keyword: str | None = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.delivery.read"))):
    return service.list_delivery_updates(db, user, keyword=keyword, page=page, page_size=page_size)


@collaboration_router.put("/orders/{order_id}/delivery-date", summary="更新订单预计交期")
def update_expected_delivery(order_id: int, data: SupplierDeliveryDateUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.delivery.update"))):
    return service.update_expected_delivery(db, user, order_id, data)


@collaboration_router.get("/shipments", response_model=SupplierShipmentPage, summary="查询供应商发货通知")
def list_shipments(keyword: str | None = None, shipment_status: str | None = Query(default=None, alias="status", pattern="^(IN_TRANSIT|RECEIVED|INSPECTING|ACCEPTED|EXCEPTION)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.shipment.read"))):
    return service.list_shipment_notices(db, user, keyword=keyword, status=shipment_status, page=page, page_size=page_size)


@collaboration_router.post("/shipments", response_model=SupplierShipmentRead, status_code=201, summary="提交供应商发货通知")
def create_shipment(data: SupplierShipmentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.shipment.submit"))):
    return service.create_shipment_notice(db, user, data)


@collaboration_router.get("/quality-documents", response_model=SupplierQualityDocumentPage, summary="查询供应商质量资料")
def list_quality_documents(keyword: str | None = None, document_status: str | None = Query(default=None, alias="status", pattern="^(SUBMITTED|ACCEPTED|REJECTED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.quality.read"))):
    return service.list_quality_documents(db, user, keyword=keyword, status=document_status, page=page, page_size=page_size)


@collaboration_router.post("/quality-documents", response_model=SupplierQualityDocumentRead, status_code=201, summary="上传供应商质量资料")
async def submit_quality_document(po_id: int = Form(..., gt=0), document_type: str = Form(...), po_item_id: int | None = Form(default=None, gt=0), note: str | None = Form(default=None, max_length=1000), file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.quality.submit"))):
    settings = file_service.get_settings()
    content = await file.read(settings.document_max_size_mb * 1024 * 1024 + 1)
    return service.create_quality_document(db, user, po_id=po_id, po_item_id=po_item_id, document_type=document_type, note=note, file_name=file.filename or "", mime_type=file.content_type or "application/octet-stream", content=content)


@collaboration_router.get("/quality-documents/{document_id}/download", summary="下载供应商已提交的质量资料")
def download_quality_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.quality.read"))):
    value, content = service.get_quality_document_file(db, user, document_id)
    return Response(content=content, media_type=value.mime_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(value.file_name)}"})


@collaboration_router.get("/reconciliations", response_model=SupplierReconciliationPage, summary="查询供应商对账记录")
def list_supplier_reconciliations(keyword: str | None = None, reconciliation_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|CONFIRMED|DISPUTED|CLOSED|CANCELLED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.reconciliation.read"))):
    return service.list_supplier_reconciliations(db, user, keyword=keyword, status=reconciliation_status, page=page, page_size=page_size)


@collaboration_router.get("/reconciliations/{reconciliation_id}/messages", response_model=SupplierReconciliationMessagePage, summary="查询对账协同留言")
def list_supplier_reconciliation_messages(reconciliation_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.reconciliation.read"))):
    return service.list_reconciliation_messages(db, user, reconciliation_id, page=page, page_size=page_size)


@collaboration_router.post("/reconciliations/{reconciliation_id}/messages", response_model=SupplierReconciliationMessageRead, status_code=201, summary="提交对账协同留言")
def add_supplier_reconciliation_message(reconciliation_id: int, data: SupplierReconciliationMessageCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.reconciliation.message"))):
    return service.add_supplier_reconciliation_message(db, user, reconciliation_id, data)


@collaboration_router.post("/reconciliations/{reconciliation_id}/confirm", summary="供应商确认对账")
def supplier_confirm_reconciliation(reconciliation_id: int, data: SupplierReconciliationAction, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.reconciliation.respond"))):
    return service.supplier_confirm_reconciliation(db, user, reconciliation_id, data.reason)


@collaboration_router.post("/reconciliations/{reconciliation_id}/dispute", summary="供应商发起对账争议")
def supplier_dispute_reconciliation(reconciliation_id: int, data: SupplierReconciliationAction, db: Session = Depends(get_db), user: User = Depends(require_permission("supplier.portal.reconciliation.respond"))):
    if not data.reason or not data.reason.strip():
        from app.core.errors import BusinessValidationError
        raise BusinessValidationError("发起对账争议必须填写原因")
    return service.supplier_dispute_reconciliation(db, user, reconciliation_id, data.reason.strip())
