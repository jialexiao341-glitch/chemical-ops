"""财务模块数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement


def get_reconciliation(db: Session, reconciliation_id: int, *, for_update: bool = False) -> FinanceReconciliation | None:
    """按主键查询对账单，可选锁定主单。"""

    statement = select(FinanceReconciliation).where(FinanceReconciliation.id == reconciliation_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def list_reconciliations(db: Session, *, scope_condition=None, status: str | None, supplier_id: int | None, page: int, page_size: int):
    """分页查询对账单。"""

    conditions = [scope_condition] if scope_condition is not None else []
    if status:
        conditions.append(FinanceReconciliation.status == status)
    if supplier_id is not None:
        conditions.append(FinanceReconciliation.supplier_id == supplier_id)
    total = db.scalar(select(func.count(FinanceReconciliation.id)).where(*conditions)) or 0
    items = list(db.scalars(select(FinanceReconciliation).where(*conditions).order_by(FinanceReconciliation.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_invoice(db: Session, invoice_id: int, *, for_update: bool = False) -> FinanceInvoice | None:
    """按主键查询发票，可选锁定记录。"""

    statement = select(FinanceInvoice).where(FinanceInvoice.id == invoice_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def list_invoices(db: Session, *, scope_condition=None, reconciliation_id: int | None, status: str | None, page: int, page_size: int):
    """分页查询发票。"""

    conditions = [scope_condition] if scope_condition is not None else []
    if reconciliation_id is not None:
        conditions.append(FinanceInvoice.reconciliation_id == reconciliation_id)
    if status:
        conditions.append(FinanceInvoice.status == status)
    total = db.scalar(select(func.count(FinanceInvoice.id)).where(*conditions)) or 0
    items = list(db.scalars(select(FinanceInvoice).where(*conditions).order_by(FinanceInvoice.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_payment(db: Session, payment_id: int, *, for_update: bool = False) -> FinancePayment | None:
    """按主键查询付款记录，可选锁定记录。"""

    statement = select(FinancePayment).where(FinancePayment.id == payment_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_payments(db: Session, *, scope_condition=None, reconciliation_id: int | None, status: str | None, page: int, page_size: int):
    """分页查询付款记录。"""

    conditions = [scope_condition] if scope_condition is not None else []
    if reconciliation_id is not None:
        conditions.append(FinancePayment.reconciliation_id == reconciliation_id)
    if status:
        conditions.append(FinancePayment.status == status)
    total = db.scalar(select(func.count(FinancePayment.id)).where(*conditions)) or 0
    items = list(db.scalars(select(FinancePayment).where(*conditions).order_by(FinancePayment.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total


def get_settlement(db: Session, settlement_id: int, *, for_update: bool = False) -> FinanceSettlement | None:
    """按主键查询结算单，可选锁定记录。"""

    statement = select(FinanceSettlement).where(FinanceSettlement.id == settlement_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_settlements(db: Session, *, scope_condition=None, status: str | None, supplier_id: int | None, page: int, page_size: int):
    """分页查询结算单。"""

    conditions = [scope_condition] if scope_condition is not None else []
    if status:
        conditions.append(FinanceSettlement.status == status)
    if supplier_id is not None:
        conditions.append(FinanceSettlement.supplier_id == supplier_id)
    total = db.scalar(select(func.count(FinanceSettlement.id)).where(*conditions)) or 0
    items = list(db.scalars(select(FinanceSettlement).where(*conditions).order_by(FinanceSettlement.id.desc()).offset((page - 1) * page_size).limit(page_size)).all())
    return items, total
