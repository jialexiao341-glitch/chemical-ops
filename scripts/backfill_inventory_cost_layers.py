"""为历史入库流水补建库存成本层。"""

from decimal import Decimal

from sqlalchemy import select

import app.main  # noqa: F401  # 载入全部模型，保证 SQLAlchemy 外键元数据完整
from app.core.db import SessionLocal
from app.modules.deliveries.model import DeliveryItem
from app.modules.inventory.model import InventoryTransaction
from app.modules.inventory_cost.model import InventoryCostLayer
from app.modules.purchase_orders.model import PurchaseOrderItem


def main() -> None:
    """按采购订单含税单价为历史入库流水建立 FIFO 成本层。"""
    db = SessionLocal()
    created = 0
    try:
        transactions = db.scalars(select(InventoryTransaction).where(InventoryTransaction.transaction_type == "INBOUND")).all()
        for transaction in transactions:
            if db.scalar(select(InventoryCostLayer).where(InventoryCostLayer.source_transaction_id == transaction.id)) is not None:
                continue
            if transaction.delivery_item_id is None:
                continue
            delivery_item = db.get(DeliveryItem, transaction.delivery_item_id)
            po_item = db.get(PurchaseOrderItem, delivery_item.po_item_id) if delivery_item is not None else None
            tax_rate = po_item.tax_rate if po_item is not None and po_item.tax_rate is not None else Decimal("0")
            unit_cost = po_item.unit_price * (Decimal("1") + tax_rate / Decimal("100")) if po_item is not None else Decimal("0")
            db.add(InventoryCostLayer(source_transaction_id=transaction.id, warehouse_id=transaction.warehouse_id, location_id=transaction.location_id, product_id=transaction.product_id, batch_id=transaction.batch_id, unit_id=transaction.unit_id, unit_cost=unit_cost, currency_code="CNY", original_quantity=transaction.quantity, remaining_quantity=transaction.quantity))
            created += 1
        db.commit()
        print("inventory_cost_backfill_ready=true")
        print(f"created_layer_count={created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
