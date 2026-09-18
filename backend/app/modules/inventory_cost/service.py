"""库存成本层、FIFO 出库和有效期预警业务逻辑。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, Warehouse, WarehouseLocation
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer, InventoryFifoOutboundAllocation, InventoryFifoOutboundRequest
from app.modules.inventory_cost.schema import FifoOutboundCreate
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User


def _require_request(db: Session, request_id: int) -> InventoryFifoOutboundRequest:
    """查询 FIFO 出库请求及分摊。"""
    value = db.scalar(select(InventoryFifoOutboundRequest).where(InventoryFifoOutboundRequest.id == request_id))
    if value is None:
        raise ResourceNotFoundError(f"FIFO 出库请求 {request_id} 不存在")
    value.allocations = list(db.scalars(select(InventoryFifoOutboundAllocation).where(InventoryFifoOutboundAllocation.request_id == request_id).order_by(InventoryFifoOutboundAllocation.id)).all())
    return value


def allocate_outbound_cost(db: Session, transaction: InventoryTransaction, quantity: Decimal) -> Decimal:
    """按 FIFO 扣减普通出库的成本层，并记录统一成本分摊。"""
    layers = list(db.scalars(
        select(InventoryCostLayer)
        .where(
            InventoryCostLayer.product_id == transaction.product_id,
            InventoryCostLayer.warehouse_id == transaction.warehouse_id,
            InventoryCostLayer.location_id == transaction.location_id,
            InventoryCostLayer.unit_id == transaction.unit_id,
            InventoryCostLayer.remaining_quantity > 0,
        )
        .order_by(InventoryCostLayer.created_at, InventoryCostLayer.id)
        .with_for_update()
    ).all())
    if sum((layer.remaining_quantity for layer in layers), Decimal("0")) < quantity:
        raise BusinessValidationError("库存成本层不足，请先执行历史库存成本回填")
    remaining = quantity
    total_cost = Decimal("0")
    for layer in layers:
        if remaining <= 0:
            break
        allocated = min(remaining, layer.remaining_quantity)
        layer.remaining_quantity -= allocated
        allocation_cost = allocated * layer.unit_cost
        db.add(InventoryCostAllocation(transaction_id=transaction.id, cost_layer_id=layer.id, quantity=allocated, unit_cost=layer.unit_cost, total_cost=allocation_cost))
        remaining -= allocated
        total_cost += allocation_cost
    return total_cost


def create_fifo_outbound(db: Session, user: User, data: FifoOutboundCreate) -> InventoryFifoOutboundRequest:
    """按成本层创建一次 FIFO 出库，并用 request_no 防止重试重复扣减。"""
    existing = db.scalar(select(InventoryFifoOutboundRequest).where(InventoryFifoOutboundRequest.request_no == data.request_no))
    if existing is not None:
        if existing.product_id == data.product_id and existing.requested_quantity == data.quantity:
            return _require_request(db, existing.id)
        raise DuplicateResourceError("FIFO 出库请求号已经用于其他出库请求")
    product = db.get(Product, data.product_id)
    warehouse = db.get(Warehouse, data.warehouse_id)
    location = db.get(WarehouseLocation, data.location_id)
    unit = db.get(Unit, data.unit_id)
    if product is None or product.status != "ACTIVE":
        raise BusinessValidationError("产品不存在或已停用")
    if warehouse is None or warehouse.status != "ACTIVE":
        raise BusinessValidationError("仓库不存在或已停用")
    if location is None or location.status != "ACTIVE" or location.warehouse_id != warehouse.id:
        raise BusinessValidationError("库位不存在、已停用或不属于指定仓库")
    if unit is None or unit.status != "ACTIVE":
        raise BusinessValidationError("计量单位不存在或已停用")
    try:
        layers = list(db.scalars(select(InventoryCostLayer).where(InventoryCostLayer.product_id == data.product_id, InventoryCostLayer.warehouse_id == data.warehouse_id, InventoryCostLayer.location_id == data.location_id, InventoryCostLayer.unit_id == data.unit_id, InventoryCostLayer.remaining_quantity > 0).order_by(InventoryCostLayer.created_at, InventoryCostLayer.id).with_for_update()).all())
        remaining = data.quantity
        if sum((layer.remaining_quantity for layer in layers), Decimal("0")) < remaining:
            raise BusinessValidationError("FIFO 成本层可用库存不足，请先建立成本层或使用普通批次出库")
        request = InventoryFifoOutboundRequest(request_no=data.request_no, product_id=data.product_id, warehouse_id=data.warehouse_id, location_id=data.location_id, unit_id=data.unit_id, requested_quantity=data.quantity, issued_quantity=Decimal("0"), total_cost=Decimal("0"), currency_code="CNY", status="COMPLETED", operator_id=user.id, note=data.note)
        db.add(request)
        db.flush()
        total_cost = Decimal("0")
        for layer in layers:
            if remaining <= 0:
                break
            balance = db.scalar(select(InventoryBalance).where(InventoryBalance.warehouse_id == data.warehouse_id, InventoryBalance.location_id == data.location_id, InventoryBalance.product_id == data.product_id, InventoryBalance.batch_id == layer.batch_id, InventoryBalance.unit_id == data.unit_id).with_for_update())
            if balance is None or balance.status != "AVAILABLE" or balance.quantity - balance.locked_quantity < min(remaining, layer.remaining_quantity):
                raise BusinessValidationError(f"批次 {layer.batch_id} 可用库存不足或已冻结")
            allocated = min(remaining, layer.remaining_quantity)
            balance.quantity -= allocated
            layer.remaining_quantity -= allocated
            allocation_cost = allocated * layer.unit_cost
            db.add(InventoryFifoOutboundAllocation(request_id=request.id, cost_layer_id=layer.id, batch_id=layer.batch_id, quantity=allocated, unit_cost=layer.unit_cost, total_cost=allocation_cost))
            transaction = InventoryTransaction(transaction_no=f"TEMP-FIFO-{request.id}-{layer.id}", transaction_type="OUTBOUND", warehouse_id=data.warehouse_id, location_id=data.location_id, product_id=data.product_id, batch_id=layer.batch_id, unit_id=data.unit_id, quantity=allocated, source_type="FIFO_OUTBOUND", source_id=request.id, operator_id=user.id, note=data.note)
            db.add(transaction)
            db.flush()
            transaction.transaction_no = f"IT{date.today():%Y%m%d}{transaction.id:06d}"
            db.add(InventoryCostAllocation(transaction_id=transaction.id, cost_layer_id=layer.id, quantity=allocated, unit_cost=layer.unit_cost, total_cost=allocation_cost))
            remaining -= allocated
            total_cost += allocation_cost
        request.issued_quantity = data.quantity
        request.total_cost = total_cost
        add_audit_log(db, actor_id=user.id, action_type="FIFO_OUTBOUND", resource_type="INVENTORY_FIFO_OUTBOUND", resource_id=request.id, request_summary="执行 FIFO 库存出库", result_status="SUCCESS")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _require_request(db, request.id)


def list_expiry_alerts(db: Session, *, days: int):
    """查询未来指定天数内到期且仍有库存的批次。"""
    today = date.today()
    deadline = date.fromordinal(today.toordinal() + days)
    rows = db.execute(select(InventoryBatch, InventoryBalance).join(InventoryBalance, InventoryBalance.batch_id == InventoryBatch.id).where(InventoryBatch.expiry_date.is_not(None), InventoryBatch.expiry_date <= deadline, InventoryBalance.quantity > 0).order_by(InventoryBatch.expiry_date, InventoryBatch.id)).all()
    result = []
    for batch, balance in rows:
        days_remaining = (batch.expiry_date - today).days
        result.append((batch, balance, days_remaining, "EXPIRED" if days_remaining < 0 else "URGENT" if days_remaining <= 7 else "WARNING"))
    return result
