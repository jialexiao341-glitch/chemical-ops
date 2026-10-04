"""供应商门户账号绑定数据模型。"""

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SupplierPortalAccount(Base):
    """将系统登录用户绑定到一个供应商。"""

    __tablename__ = "supplier_portal_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3))


class SupplierDeliveryUpdate(Base):
    """供应商提交的订单预计交期变更历史。"""

    __tablename__ = "supplier_delivery_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    previous_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class SupplierQualityDocument(Base):
    """供应商提交给订单的质量资料及审核状态。"""

    __tablename__ = "supplier_quality_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    po_item_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_order_items.id"), nullable=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("sys_files.id"), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUBMITTED")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class SupplierReconciliationMessage(Base):
    """供应商与采购方在对账单上的追加式协同留言。"""

    __tablename__ = "supplier_reconciliation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("finance_reconciliations.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
