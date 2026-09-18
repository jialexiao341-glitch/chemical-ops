"""库存成本层和 FIFO 出库数据模型。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InventoryCostLayer(Base):
    """一笔入库形成的 FIFO 成本层。"""
    __tablename__ = "inventory_cost_layers"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_transaction_id: Mapped[int] = mapped_column(ForeignKey("inventory_transactions.id"), nullable=False, unique=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class InventoryCostAllocation(Base):
    """普通领用、调拨和退货出库对应的成本层分摊。"""
    __tablename__ = "inventory_cost_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("inventory_transactions.id"), nullable=False)
    cost_layer_id: Mapped[int] = mapped_column(ForeignKey("inventory_cost_layers.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class InventoryFifoOutboundRequest(Base):
    """一次 FIFO 出库请求，request_no 用于防止重复执行。"""
    __tablename__ = "inventory_fifo_outbound_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("md_products.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(ForeignKey("md_units.id"), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    issued_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    operator_id: Mapped[int] = mapped_column(ForeignKey("sys_users.id"), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))


class InventoryFifoOutboundAllocation(Base):
    """FIFO 出库在各成本层上的数量分摊。"""
    __tablename__ = "inventory_fifo_outbound_allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("inventory_fifo_outbound_requests.id"), nullable=False)
    cost_layer_id: Mapped[int] = mapped_column(ForeignKey("inventory_cost_layers.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("inventory_batches.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
