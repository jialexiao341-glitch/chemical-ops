"""库存模块的数据访问操作。"""

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, selectinload

from app.modules.inventory.model import (
    InventoryBalance,
    InventoryBalanceStatusLog,
    InventoryBatch,
    InventoryIssueRequest,
    InventoryTransaction,
    InventoryTransferRequest,
    InventoryStocktakeRequest,
    Warehouse,
    WarehouseLocation,
)


def get_warehouse(db: Session, warehouse_id: int) -> Warehouse | None:
    """查询仓库。"""

    return db.get(Warehouse, warehouse_id)


def get_location(db: Session, location_id: int) -> WarehouseLocation | None:
    """查询库位。"""

    return db.get(WarehouseLocation, location_id)


def get_batch(db: Session, product_id: int, batch_no: str, source_delivery_id: int) -> InventoryBatch | None:
    """按产品、批次号和来源到货单查询库存批次。"""

    return db.scalar(
        select(InventoryBatch).where(
            InventoryBatch.product_id == product_id,
            InventoryBatch.batch_no == batch_no,
            InventoryBatch.source_delivery_id == source_delivery_id,
        )
    )


def get_balance(
    db: Session,
    warehouse_id: int,
    location_id: int,
    product_id: int,
    batch_id: int,
    unit_id: int,
    *,
    for_update: bool = False,
) -> InventoryBalance | None:
    """查询指定库存位置的余额，可选锁定余额行。"""

    statement = select(InventoryBalance).where(
        InventoryBalance.warehouse_id == warehouse_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_id == product_id,
        InventoryBalance.batch_id == batch_id,
        InventoryBalance.unit_id == unit_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def ensure_balance_for_update(
    db: Session,
    warehouse_id: int,
    location_id: int,
    product_id: int,
    batch_id: int,
    unit_id: int,
) -> InventoryBalance | None:
    """原子确保库存余额存在，再以统一顺序锁定余额行。"""

    db.execute(
        insert(InventoryBalance).prefix_with("IGNORE").values(
            warehouse_id=warehouse_id,
            location_id=location_id,
            product_id=product_id,
            batch_id=batch_id,
            unit_id=unit_id,
            quantity=0,
            locked_quantity=0,
            status="AVAILABLE",
        )
    )
    return get_balance(db, warehouse_id, location_id, product_id, batch_id, unit_id, for_update=True)

def get_balance_by_id(db: Session, balance_id: int, *, for_update: bool = False) -> InventoryBalance | None:
    """按主键查询库存余额，可选锁定余额行。"""

    statement = select(InventoryBalance).where(InventoryBalance.id == balance_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_balance_status_logs(db: Session, balance_id: int, *, page: int, page_size: int) -> tuple[list[InventoryBalanceStatusLog], int]:
    """分页查询库存余额状态变更记录。"""

    condition = InventoryBalanceStatusLog.balance_id == balance_id
    total = db.scalar(select(func.count(InventoryBalanceStatusLog.id)).where(condition)) or 0
    items = list(
        db.scalars(
            select(InventoryBalanceStatusLog)
            .where(condition)
            .order_by(InventoryBalanceStatusLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_transaction_by_delivery_item(db: Session, delivery_item_id: int) -> InventoryTransaction | None:
    """查询到货明细是否已生成入库流水。"""

    return db.scalar(select(InventoryTransaction).where(InventoryTransaction.delivery_item_id == delivery_item_id))


def list_balances(db: Session, *, product_id: int | None, warehouse_id: int | None, batch_id: int | None = None, warehouse_ids: set[int] | None = None, page: int, page_size: int) -> tuple[list[InventoryBalance], int]:
    """分页查询库存余额。"""

    conditions = []
    if product_id is not None:
        conditions.append(InventoryBalance.product_id == product_id)
    if warehouse_id is not None:
        conditions.append(InventoryBalance.warehouse_id == warehouse_id)
    if batch_id is not None:
        conditions.append(InventoryBalance.batch_id == batch_id)
    if warehouse_ids is not None:
        conditions.append(InventoryBalance.warehouse_id.in_(warehouse_ids))
    total = db.scalar(select(func.count(InventoryBalance.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(InventoryBalance).where(*conditions).order_by(InventoryBalance.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def list_transactions(db: Session, *, product_id: int | None, transaction_type: str | None, warehouse_ids: set[int] | None = None, page: int, page_size: int) -> tuple[list[InventoryTransaction], int]:
    """分页查询库存流水。"""

    conditions = []
    if product_id is not None:
        conditions.append(InventoryTransaction.product_id == product_id)
    if transaction_type:
        conditions.append(InventoryTransaction.transaction_type == transaction_type)
    if warehouse_ids is not None:
        conditions.append(InventoryTransaction.warehouse_id.in_(warehouse_ids))
    total = db.scalar(select(func.count(InventoryTransaction.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(InventoryTransaction).where(*conditions).order_by(InventoryTransaction.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_issue_request(db: Session, issue_id: int, *, for_update: bool = False) -> InventoryIssueRequest | None:
    """查询库存领用申请，可选锁定主单。"""

    statement = select(InventoryIssueRequest).options(selectinload(InventoryIssueRequest.items)).where(InventoryIssueRequest.id == issue_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_issue_requests(db: Session, *, applicant_id: int | None, status: str | None, page: int, page_size: int) -> tuple[list[InventoryIssueRequest], int]:
    """按申请人和状态分页查询库存领用申请。"""

    conditions = []
    if applicant_id is not None:
        conditions.append(InventoryIssueRequest.applicant_id == applicant_id)
    if status:
        conditions.append(InventoryIssueRequest.status == status)
    total = db.scalar(select(func.count(InventoryIssueRequest.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(InventoryIssueRequest)
            .options(selectinload(InventoryIssueRequest.items))
            .where(*conditions)
            .order_by(InventoryIssueRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_transfer_request(db: Session, transfer_id: int, *, for_update: bool = False) -> InventoryTransferRequest | None:
    """查询库存调拨申请，可选锁定主单。"""

    statement = select(InventoryTransferRequest).options(selectinload(InventoryTransferRequest.items)).where(InventoryTransferRequest.id == transfer_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_transfer_requests(db: Session, *, applicant_id: int | None, status: str | None, page: int, page_size: int) -> tuple[list[InventoryTransferRequest], int]:
    """按申请人和状态分页查询库存调拨申请。"""

    conditions = []
    if applicant_id is not None:
        conditions.append(InventoryTransferRequest.applicant_id == applicant_id)
    if status:
        conditions.append(InventoryTransferRequest.status == status)
    total = db.scalar(select(func.count(InventoryTransferRequest.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(InventoryTransferRequest)
            .options(selectinload(InventoryTransferRequest.items))
            .where(*conditions)
            .order_by(InventoryTransferRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_stocktake_request(db: Session, stocktake_id: int, *, for_update: bool = False) -> InventoryStocktakeRequest | None:
    """查询库存盘点申请，可选锁定主单。"""

    statement = select(InventoryStocktakeRequest).options(selectinload(InventoryStocktakeRequest.items)).where(InventoryStocktakeRequest.id == stocktake_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_stocktake_requests(db: Session, *, applicant_id: int | None, status: str | None, page: int, page_size: int) -> tuple[list[InventoryStocktakeRequest], int]:
    """按申请人和状态分页查询库存盘点申请。"""

    conditions = []
    if applicant_id is not None:
        conditions.append(InventoryStocktakeRequest.applicant_id == applicant_id)
    if status:
        conditions.append(InventoryStocktakeRequest.status == status)
    total = db.scalar(select(func.count(InventoryStocktakeRequest.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(InventoryStocktakeRequest)
            .options(selectinload(InventoryStocktakeRequest.items))
            .where(*conditions)
            .order_by(InventoryStocktakeRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total
