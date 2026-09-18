"""仓库、库位、库存批次、库存余额和库存流水的数据模型。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.modules.products.category_model import ProductCategory
from app.modules.suppliers.product_model import SupplierProduct
from app.modules.system.file_model import SysFile
from app.modules.purchase_requests.model import Unit
from app.modules.system.model import Department, User


class Warehouse(Base):
    """仓库主数据。"""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    warehouse_name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class WarehouseLocation(Base):
    """仓库库位。"""

    __tablename__ = "warehouse_locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "location_code", name="uk_location_warehouse_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(64), nullable=False)
    location_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class InventoryBatch(Base):
    """库存批次。"""

    __tablename__ = "inventory_batches"
    __table_args__ = (UniqueConstraint("product_id", "batch_no", "source_delivery_id", name="uk_inventory_batch_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(128), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    source_delivery_id: Mapped[int | None] = mapped_column(ForeignKey("deliveries.id"), nullable=True)
    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class InventoryBalance(Base):
    """按仓库、库位、产品和批次汇总的库存余额。"""

    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "location_id", "product_id", "batch_id", "unit_id", name="uk_inventory_balance_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    locked_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="AVAILABLE")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )


class InventoryBalanceStatusLog(Base):
    """库存余额冻结和解冻历史。"""

    __tablename__ = "inventory_balance_status_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    balance_id: Mapped[int] = mapped_column(ForeignKey("inventory_balances.id"), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    operator_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class InventoryTransaction(Base):
    """库存数量变动流水。"""

    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    delivery_item_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_items.id"), nullable=True, unique=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[int | None] = mapped_column(nullable=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class InventoryIssueRequest(Base):
    """库存领用申请主单。"""

    __tablename__ = "inventory_issue_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("sys_departments.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["InventoryIssueItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="InventoryIssueItem.line_no"
    )


class InventoryIssueItem(Base):
    """库存领用申请明细。"""

    __tablename__ = "inventory_issue_items"
    __table_args__ = (UniqueConstraint("issue_request_id", "line_no", name="uk_inventory_issue_item_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_request_id: Mapped[int] = mapped_column(ForeignKey("inventory_issue_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    issued_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    request: Mapped[InventoryIssueRequest] = relationship(back_populates="items")


class InventoryTransferRequest(Base):
    """库存调拨申请主单。"""

    __tablename__ = "inventory_transfer_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["InventoryTransferItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="InventoryTransferItem.line_no"
    )


class InventoryTransferItem(Base):
    """库存调拨申请明细。"""

    __tablename__ = "inventory_transfer_items"
    __table_args__ = (UniqueConstraint("transfer_request_id", "line_no", name="uk_inventory_transfer_item_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_request_id: Mapped[int] = mapped_column(ForeignKey("inventory_transfer_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    source_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    source_location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    target_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    target_location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    transferred_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    request: Mapped[InventoryTransferRequest] = relationship(back_populates="items")


class InventoryStocktakeRequest(Base):
    """库存盘点申请主单。"""

    __tablename__ = "inventory_stocktake_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=True)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("sys_users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    items: Mapped[list["InventoryStocktakeItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="InventoryStocktakeItem.line_no"
    )


class InventoryStocktakeItem(Base):
    """库存盘点明细。"""

    __tablename__ = "inventory_stocktake_items"
    __table_args__ = (UniqueConstraint("stocktake_request_id", "line_no", name="uk_inventory_stocktake_item_line"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_request_id: Mapped[int] = mapped_column(ForeignKey("inventory_stocktake_requests.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    book_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    difference_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    request: Mapped[InventoryStocktakeRequest] = relationship(back_populates="items")
