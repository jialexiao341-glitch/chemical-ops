"""财务对账、发票、付款和结算 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.core.errors import BusinessValidationError
from app.modules.finance import service, reconciliation_items, invoice_matches
from app.modules.finance.schema import (
    InvoiceCreate,
    InvoicePage,
    InvoiceRead,
    InvoiceReject,
    InvoiceMatchRead,
    InvoiceMatchSave,
    PaymentCreate,
    PaymentPage,
    PaymentPaid,
    PaymentRead,
    PaymentReject,
    ReconciliationAction,
    ReconciliationItemsRead,
    ReconciliationItemsRefresh,
    ReconciliationCreate,
    ReconciliationPage,
    ReconciliationRead,
    SettlementCancel,
    SettlementCreate,
    SettlementPage,
    SettlementRead,
)
from app.modules.system.model import User


router = APIRouter(prefix="/finance", tags=["财务管理"])


@router.get("/invoices/{invoice_id}/matches", response_model=InvoiceMatchRead, summary="查看发票行匹配和历史版本")
def read_invoice_matches(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.read"))):
    return invoice_matches.read_match(db, user, invoice_id)


@router.post("/invoices/{invoice_id}/matches", response_model=InvoiceMatchRead, summary="保存发票人工行匹配")
def save_invoice_matches(invoice_id: int, data: InvoiceMatchSave, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.write"))):
    return invoice_matches.save_match(db, user, invoice_id, data)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceRead, summary="作废未核验发票并释放匹配额度")
def void_invoice(invoice_id: int, data: InvoiceReject, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.write"))):
    return invoice_matches.void_invoice(db, user, invoice_id, data.reason)


@router.post("/reconciliations", response_model=ReconciliationRead, status_code=status.HTTP_201_CREATED, summary="创建财务对账单")
def create_reconciliation(data: ReconciliationCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.write"))) -> ReconciliationRead:
    """为已完成收货且质量验收通过的采购订单创建对账单。"""

    return service.create_reconciliation(db, user, data.po_id, data.note)


@router.get("/reconciliations", response_model=ReconciliationPage, summary="分页查询财务对账单")
def list_reconciliations(status_value: str | None = Query(default=None, alias="status", pattern="^(DRAFT|CONFIRMED|DISPUTED|CLOSED|CANCELLED)$"), supplier_id: int | None = Query(default=None, gt=0), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_permission("finance.reconciliations.read"))) -> ReconciliationPage:
    """按状态和供应商分页查询对账单。"""

    items, total = service.list_reconciliations(db, _, status=status_value, supplier_id=supplier_id, page=page, page_size=page_size)
    return ReconciliationPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/reconciliations/{reconciliation_id}", response_model=ReconciliationRead, summary="查询财务对账单详情")
def get_reconciliation(reconciliation_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.read"))) -> ReconciliationRead:
    """查询一张对账单详情。"""

    return service.get_reconciliation(db, user, reconciliation_id)


@router.get("/reconciliations/{reconciliation_id}/items", response_model=ReconciliationItemsRead, summary="查看对账明细与历史版本")
def get_reconciliation_items(reconciliation_id: int, version: int | None = Query(default=None, gt=0), db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.read"))):
    return reconciliation_items.read_items(db, user, reconciliation_id, version)


@router.post("/reconciliations/{reconciliation_id}/items/refresh", response_model=ReconciliationItemsRead, summary="重新核对并保存退货处理口径")
def refresh_reconciliation_items(reconciliation_id: int, data: ReconciliationItemsRefresh, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.write"))):
    return reconciliation_items.refresh_items(db, user, reconciliation_id, data)


@router.post("/reconciliations/{reconciliation_id}/confirm", response_model=ReconciliationRead, summary="确认财务对账单")
def confirm_reconciliation(reconciliation_id: int, data: ReconciliationAction, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.write"))) -> ReconciliationRead:
    """确认对账单，确认后才能发起付款。"""

    return service.confirm_reconciliation(db, user, reconciliation_id, data.reason)


@router.post("/reconciliations/{reconciliation_id}/dispute", response_model=ReconciliationRead, summary="发起财务对账争议")
def dispute_reconciliation(reconciliation_id: int, data: ReconciliationAction, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.reconciliations.write"))) -> ReconciliationRead:
    """标记对账争议并保存原因。"""

    if not data.reason:
        raise BusinessValidationError("发起对账争议必须填写原因")
    return service.dispute_reconciliation(db, user, reconciliation_id, data.reason)


@router.post("/invoices", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED, summary="录入供应商发票")
def create_invoice(data: InvoiceCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.write"))) -> InvoiceRead:
    """将发票金额纳入对账单并等待核验。"""

    return service.create_invoice(db, user, data)


@router.get("/invoices", response_model=InvoicePage, summary="分页查询供应商发票")
def list_invoices(reconciliation_id: int | None = Query(default=None, gt=0), invoice_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|VERIFIED|REJECTED|VOIDED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_permission("finance.invoices.read"))) -> InvoicePage:
    """按对账单和状态分页查询发票。"""

    items, total = service.list_invoices(db, _, reconciliation_id=reconciliation_id, status=invoice_status, page=page, page_size=page_size)
    return InvoicePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead, summary="查询供应商发票详情")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("finance.invoices.read"))) -> InvoiceRead:
    """查询发票详情。"""

    return service.get_invoice(db, _, invoice_id)


@router.post("/invoices/{invoice_id}/submit", response_model=InvoiceRead, summary="提交发票核验")
def submit_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.write"))) -> InvoiceRead:
    """提交发票进入财务核验。"""

    return service.submit_invoice(db, user, invoice_id)


@router.post("/invoices/{invoice_id}/verify", response_model=InvoiceRead, summary="人工复核发票")
def verify_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.verify"))) -> InvoiceRead:
    """记录内部人工复核结果；不调用税务平台，也不代表已完成税务验真。"""

    return service.verify_invoice(db, user, invoice_id)


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceRead, summary="驳回发票")
def reject_invoice(invoice_id: int, data: InvoiceReject, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.invoices.verify"))) -> InvoiceRead:
    """驳回发票并保留原因。"""

    return service.reject_invoice(db, user, invoice_id, data.reason)


@router.post("/payments", response_model=PaymentRead, status_code=status.HTTP_201_CREATED, summary="发起付款申请")
def create_payment(data: PaymentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.payments.write"))) -> PaymentRead:
    """对已确认对账单发起付款申请。"""

    return service.create_payment(db, user, data)


@router.get("/payments", response_model=PaymentPage, summary="分页查询付款记录")
def list_payments(reconciliation_id: int | None = Query(default=None, gt=0), payment_status: str | None = Query(default=None, alias="status", pattern="^(REQUESTED|APPROVED|PAID|REJECTED|CANCELLED)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_permission("finance.payments.read"))) -> PaymentPage:
    """按对账单和状态分页查询付款记录。"""

    items, total = service.list_payments(db, _, reconciliation_id=reconciliation_id, status=payment_status, page=page, page_size=page_size)
    return PaymentPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/payments/{payment_id}", response_model=PaymentRead, summary="查询付款详情")
def get_payment(payment_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("finance.payments.read"))) -> PaymentRead:
    """查询付款申请和付款结果。"""

    return service.get_payment(db, _, payment_id)


@router.post("/payments/{payment_id}/approve", response_model=PaymentRead, summary="审批付款申请")
def approve_payment(payment_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.payments.approve"))) -> PaymentRead:
    """审批付款申请。"""

    return service.approve_payment(db, user, payment_id)


@router.post("/payments/{payment_id}/reject", response_model=PaymentRead, summary="驳回付款申请")
def reject_payment(payment_id: int, data: PaymentReject, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.payments.approve"))) -> PaymentRead:
    """驳回付款申请并保留原因。"""

    return service.reject_payment(db, user, payment_id, data.reason)


@router.post("/payments/{payment_id}/paid", response_model=PaymentRead, summary="登记人工核对的付款结果")
def mark_payment_paid(payment_id: int, data: PaymentPaid, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.payments.write"))) -> PaymentRead:
    """记录人工核对的外部流水；此接口不会向银行查询或发送支付指令。"""

    return service.mark_payment_paid(db, user, payment_id, data.transaction_ref, data.note)


@router.post("/settlements", response_model=SettlementRead, status_code=status.HTTP_201_CREATED, summary="创建采购结算单")
def create_settlement(data: SettlementCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.settlements.write"))) -> SettlementRead:
    """为已足额付款的对账单创建结算单。"""

    return service.create_settlement(db, user, data)


@router.get("/settlements", response_model=SettlementPage, summary="分页查询采购结算单")
def list_settlements(settlement_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|CONFIRMED|CANCELLED)$"), supplier_id: int | None = Query(default=None, gt=0), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_permission("finance.settlements.read"))) -> SettlementPage:
    """按状态和供应商分页查询结算单。"""

    items, total = service.list_settlements(db, _, status=settlement_status, supplier_id=supplier_id, page=page, page_size=page_size)
    return SettlementPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/settlements/{settlement_id}", response_model=SettlementRead, summary="查询采购结算单详情")
def get_settlement(settlement_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("finance.settlements.read"))) -> SettlementRead:
    """查询结算单详情。"""

    return service.get_settlement(db, _, settlement_id)


@router.post("/settlements/{settlement_id}/confirm", response_model=SettlementRead, summary="确认采购结算单")
def confirm_settlement(settlement_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.settlements.approve"))) -> SettlementRead:
    """确认结算单并关闭对应对账单。"""

    return service.confirm_settlement(db, user, settlement_id)


@router.post("/settlements/{settlement_id}/cancel", response_model=SettlementRead, summary="取消采购结算单")
def cancel_settlement(settlement_id: int, data: SettlementCancel, db: Session = Depends(get_db), user: User = Depends(require_permission("finance.settlements.write"))) -> SettlementRead:
    """取消尚未确认的结算单。"""

    return service.cancel_settlement(db, user, settlement_id, data.reason)
