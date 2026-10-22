"""询价单、供应商报价和比价结果的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, JSON, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.modules.purchase_requests.model import Unit
from app.modules.products.category_model import ProductCategory
from app.modules.system.file_model import SysFile
from app.modules.suppliers.product_model import SupplierProduct


class RFQ(Base):
    """询价单主表。"""

    __tablename__ = "rfqs"

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    source_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"), nullable=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    quote_deadline: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_requirements: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    sent_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["RFQItem"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="RFQItem.line_no"
    )
    suppliers: Mapped[list["RFQSupplier"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan"
    )
    quotes: Mapped[list["SupplierQuote"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="SupplierQuote.id"
    )
    comparisons: Mapped[list["QuoteComparison"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="QuoteComparison.id"
    )


class RFQItem(Base):
    """询价单明细。"""

    __tablename__ = "rfq_items"
    __table_args__ = (UniqueConstraint("rfq_id", "line_no", name="uk_rfq_items_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source_request_item_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_request_items.id"), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("md_products.id"), nullable=True)
    requested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specification: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    required_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    technical_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    rfq: Mapped[RFQ] = relationship(back_populates="items")


class RFQSupplier(Base):
    """询价单邀请的供应商。"""

    __tablename__ = "rfq_suppliers"

    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id"), primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), primary_key=True)
    invited_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    response_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    response_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    invitation_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    rfq: Mapped[RFQ] = relationship(back_populates="suppliers")


class SupplierQuote(Base):
    """供应商报价主单。"""

    __tablename__ = "supplier_quotes"
    __table_args__ = (UniqueConstraint("rfq_id", "supplier_id", "quote_version", name="uk_supplier_quotes_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    quote_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("sys_files.id"), nullable=True)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    rfq: Mapped[RFQ] = relationship(back_populates="quotes")
    items: Mapped[list["SupplierQuoteItem"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="SupplierQuoteItem.id"
    )


class SupplierQuoteItem(Base):
    """供应商报价明细。"""

    __tablename__ = "supplier_quote_items"
    __table_args__ = (UniqueConstraint("quote_id", "rfq_item_id", name="uk_supplier_quote_items_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=False)
    rfq_item_id: Mapped[int] = mapped_column(ForeignKey("rfq_items.id"), nullable=False)
    supplier_product_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_products.id"), nullable=True)
    supplier_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quoted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    tax_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    moq_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    moq_unit_id: Mapped[int | None] = mapped_column(ForeignKey("md_units.id"), nullable=True)
    freight_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    freight_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    freight_tax_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    quote: Mapped[SupplierQuote] = relationship(back_populates="items")


class QuoteComparison(Base):
    """一次比价快照。"""

    __tablename__ = "quote_comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    selected_quote_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    rfq: Mapped[RFQ] = relationship(back_populates="comparisons")
    items: Mapped[list["QuoteComparisonItem"]] = relationship(
        back_populates="comparison", cascade="all, delete-orphan", order_by="QuoteComparisonItem.rfq_item_id"
    )


class QuoteComparisonItem(Base):
    """比价快照中的供应商报价明细。"""

    __tablename__ = "quote_comparison_items"
    __table_args__ = (UniqueConstraint("comparison_id", "quote_id", "rfq_item_id", name="uk_quote_comparison_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("quote_comparisons.id"), nullable=False)
    quote_id: Mapped[int] = mapped_column(ForeignKey("supplier_quotes.id"), nullable=False)
    rfq_item_id: Mapped[int] = mapped_column(ForeignKey("rfq_items.id"), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    quoted_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    tax_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comparison_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_COMPARABLE")
    comparison_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    moq_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)
    freight_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    freight_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    freight_tax_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    analysis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    historical_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    composite_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    rank_no: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    selection_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    @property
    def cost_analysis(self) -> dict | None:
        return self.analysis_json

    comparison: Mapped[QuoteComparison] = relationship(back_populates="items")
