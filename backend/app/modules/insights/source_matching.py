"""Match inventory movements to one executed document line without guessing."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.inventory.model import (
    InventoryBatch, InventoryIssueItem, InventoryIssueRequest,
    InventoryStocktakeItem, InventoryStocktakeRequest, InventoryTransaction,
    InventoryTransferItem, InventoryTransferRequest, WarehouseLocation,
)
from app.modules.inventory_returns.model import InventoryReturnItem, InventoryReturnRequest


def match_source(db: Session, tx: InventoryTransaction) -> dict:
    result = {"transaction_id": tx.id, "transaction_no": tx.transaction_no,
              "transaction_type": tx.transaction_type, "quantity": str(tx.quantity), "unit_id": tx.unit_id,
              "warehouse_id": tx.warehouse_id, "location_id": tx.location_id,
              "source_type": tx.source_type, "source_id": tx.source_id,
              "item_id": None, "expected_quantity": None, "signed_quantity": None,
              "status": "MISSING", "reason": "缺少可识别的来源单据或明细"}
    batch = db.get(InventoryBatch, tx.batch_id)
    location = db.get(WarehouseLocation, tx.location_id)
    if batch is None or batch.product_id != tx.product_id or location is None or location.warehouse_id != tx.warehouse_id:
        return {**result, "status": "CONFLICT", "reason": "流水的批次、产品或仓库库位关系不一致"}
    if not tx.source_id:
        return result

    source_type = tx.source_type
    candidates = []
    expected_type = "OUTBOUND"
    completed = False
    quantity_field = ""
    if source_type == "DELIVERY":
        document = db.get(Delivery, tx.source_id)
        if document is None:
            return result
        expected_type = "INBOUND"
        completed = document.status == "ACCEPTED"
        quantity_field = "actual_quantity"
        if tx.delivery_item_id is not None:
            item = db.get(DeliveryItem, tx.delivery_item_id)
            candidates = [item] if item is not None and item.delivery_id == document.id else []
        else:
            candidates = list(db.scalars(select(DeliveryItem).where(
                DeliveryItem.delivery_id == document.id, DeliveryItem.product_id == tx.product_id,
                DeliveryItem.unit_id == tx.unit_id,
            )).all())
            candidates = [item for item in candidates if (item.batch_no or f"{document.delivery_no}-{item.line_no}") == batch.batch_no]
        if batch.source_delivery_id != document.id:
            return {**result, "status": "CONFLICT", "reason": "流水来源到货单与批次来源不一致"}
    elif source_type in {"ISSUE_REQUEST", "INVENTORY_RETURN"}:
        request_model, item_model, request_field, quantity_field = (
            (InventoryIssueRequest, InventoryIssueItem, "issue_request_id", "issued_quantity")
            if source_type == "ISSUE_REQUEST" else
            (InventoryReturnRequest, InventoryReturnItem, "return_request_id", "returned_quantity")
        )
        document = db.get(request_model, tx.source_id)
        if document is None:
            return result
        completed = document.status == "COMPLETED"
        candidates = list(db.scalars(select(item_model).where(
            getattr(item_model, request_field) == tx.source_id,
            item_model.batch_id == tx.batch_id, item_model.product_id == tx.product_id,
            item_model.unit_id == tx.unit_id, item_model.warehouse_id == tx.warehouse_id,
            item_model.location_id == tx.location_id,
        )).all())
    elif source_type == "INVENTORY_STOCKTAKE":
        document = db.get(InventoryStocktakeRequest, tx.source_id)
        if document is None:
            return result
        expected_type = "ADJUSTMENT"
        completed = document.status == "COMPLETED" and document.warehouse_id == tx.warehouse_id
        quantity_field = "difference_quantity"
        candidates = list(db.scalars(select(InventoryStocktakeItem).where(
            InventoryStocktakeItem.stocktake_request_id == tx.source_id,
            InventoryStocktakeItem.batch_id == tx.batch_id, InventoryStocktakeItem.product_id == tx.product_id,
            InventoryStocktakeItem.unit_id == tx.unit_id, InventoryStocktakeItem.location_id == tx.location_id,
        )).all())
    elif source_type == "INVENTORY_TRANSFER":
        document = db.get(InventoryTransferRequest, tx.source_id)
        if document is None:
            return result
        completed = document.status == "COMPLETED"
        quantity_field = "transferred_quantity"
        if tx.transaction_type not in {"INBOUND", "OUTBOUND"}:
            return {**result, "status": "CONFLICT", "reason": "调拨流水须为出库或入库"}
        expected_type = tx.transaction_type
        prefix = "source" if expected_type == "OUTBOUND" else "target"
        candidates = list(db.scalars(select(InventoryTransferItem).where(
            InventoryTransferItem.transfer_request_id == tx.source_id,
            InventoryTransferItem.batch_id == tx.batch_id, InventoryTransferItem.product_id == tx.product_id,
            InventoryTransferItem.unit_id == tx.unit_id,
            getattr(InventoryTransferItem, f"{prefix}_warehouse_id") == tx.warehouse_id,
            getattr(InventoryTransferItem, f"{prefix}_location_id") == tx.location_id,
        )).all())
    else:
        return result

    if not candidates:
        return {**result, "status": "CONFLICT", "reason": "来源单据存在，但没有对应的批次、产品、单位及库位明细"}
    if len(candidates) != 1:
        return {**result, "status": "AMBIGUOUS", "reason": "存在多条候选明细，无法唯一匹配"}
    item = candidates[0]
    expected = getattr(item, quantity_field)
    if source_type == "DELIVERY" and (item.product_id != tx.product_id or item.unit_id != tx.unit_id or (item.batch_no or f"{document.delivery_no}-{item.line_no}") != batch.batch_no):
        return {**result, "item_id": item.id, "status": "CONFLICT", "reason": "关联到货明细的批次、产品或单位不一致"}
    result.update(item_id=item.id, expected_quantity=str(abs(expected)))
    item_statuses = {"ISSUE_REQUEST": "ISSUED", "INVENTORY_RETURN": "RETURNED", "INVENTORY_TRANSFER": "TRANSFERRED", "INVENTORY_STOCKTAKE": "ADJUSTED"}
    if source_type in item_statuses and item.status != item_statuses[source_type]:
        return {**result, "status": "CONFLICT", "reason": "来源明细尚未完成执行"}
    if tx.transaction_type != expected_type or not completed or tx.quantity <= 0 or (expected_type != "ADJUSTMENT" and expected <= 0) or tx.quantity != abs(expected):
        return {**result, "status": "CONFLICT", "reason": "流水方向、执行数量或来源单据完成状态不一致"}
    if source_type == "INVENTORY_STOCKTAKE" and item.counted_quantity - item.book_quantity != expected:
        return {**result, "status": "CONFLICT", "reason": "盘点差额与账面、实盘数量不一致"}
    signed = expected if expected_type == "ADJUSTMENT" else tx.quantity if expected_type == "INBOUND" else -tx.quantity
    return {**result, "status": "MATCHED", "reason": "已唯一匹配来源明细、方向与执行数量", "signed_quantity": str(signed)}


def match_sources(db: Session, transactions: list[InventoryTransaction]) -> dict[int, dict]:
    results = {tx.id: match_source(db, tx) for tx in transactions}
    claims = Counter((row["source_type"], row["source_id"], row["item_id"], tx.transaction_type)
                     for tx in transactions for row in [results[tx.id]] if row["item_id"] is not None)
    for tx in transactions:
        row = results[tx.id]
        key = (row["source_type"], row["source_id"], row["item_id"], tx.transaction_type)
        if row["status"] == "MATCHED" and claims[key] > 1:
            row.update(status="DUPLICATE", reason="多条同方向流水引用同一执行明细", signed_quantity=None)
    return results


def transfer_pairs(db: Session, batch_id: int, scope: set[int] | None,
                   transactions: list[InventoryTransaction], matches: dict[int, dict]) -> list[dict]:
    items = db.scalars(select(InventoryTransferItem).join(InventoryTransferRequest).where(
        InventoryTransferItem.batch_id == batch_id, InventoryTransferRequest.status == "COMPLETED",
    ).order_by(InventoryTransferItem.id)).all()
    pairs = []
    for item in items:
        source_visible = scope is None or item.source_warehouse_id in scope
        target_visible = scope is None or item.target_warehouse_id in scope
        if not source_visible and not target_visible:
            continue
        rows = [tx for tx in transactions if tx.source_type == "INVENTORY_TRANSFER"
                and tx.source_id == item.transfer_request_id and tx.product_id == item.product_id
                and tx.unit_id == item.unit_id and (
                    (tx.transaction_type == "OUTBOUND" and tx.warehouse_id == item.source_warehouse_id and tx.location_id == item.source_location_id)
                    or (tx.transaction_type == "INBOUND" and tx.warehouse_id == item.target_warehouse_id and tx.location_id == item.target_location_id))]
        outbound = [tx for tx in rows if tx.transaction_type == "OUTBOUND"]
        inbound = [tx for tx in rows if tx.transaction_type == "INBOUND"]
        if not source_visible or not target_visible:
            status = "OUT_OF_SCOPE"
        elif not outbound or not inbound:
            status = "MISSING_SIDE"
        elif len(outbound) != 1 or len(inbound) != 1:
            status = "DUPLICATE"
        elif any(matches[tx.id]["status"] != "MATCHED" or matches[tx.id]["item_id"] != item.id for tx in rows):
            status = "CONFLICT"
        else:
            status = "MATCHED"
        pairs.append({"request_id": item.transfer_request_id, "item_id": item.id, "unit_id": item.unit_id,
                      "status": status, "outbound_ids": [tx.id for tx in outbound], "inbound_ids": [tx.id for tx in inbound],
                      "outbound_quantity": str(sum(tx.quantity for tx in outbound)) if source_visible else None,
                      "inbound_quantity": str(sum(tx.quantity for tx in inbound)) if target_visible else None})
    return pairs
