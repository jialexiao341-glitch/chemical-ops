"""仓库、库存入库和库存台账的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.inventory import crud, service
from app.modules.inventory.schema import (
    InboundCreate,
    InboundRead,
    InventoryBalancePage,
    InventoryBalanceRead,
    InventoryBalanceStatusChange,
    InventoryBalanceStatusLogPage,
    InventoryIssueRequestCreate,
    InventoryIssueOptionRead,
    InventoryIssueRequestPage,
    InventoryIssueRequestRead,
    InventoryIssueRequestUpdate,
    InventoryIssueReject,
    InventoryTransactionPage,
    InventoryTransferRequestCreate,
    InventoryTransferRequestPage,
    InventoryTransferRequestRead,
    InventoryTransferRequestUpdate,
    InventoryTransferReject,
    InventoryStocktakeRequestCreate,
    InventoryStocktakeRequestPage,
    InventoryStocktakeRequestRead,
    InventoryStocktakeRequestUpdate,
    InventoryStocktakeReject,
    LocationCreate,
    LocationRead,
    WarehouseCreate,
    WarehouseRead,
)
from app.modules.system.model import User


router = APIRouter(prefix="/inventory", tags=["库存管理"])


@router.post("/warehouses", response_model=WarehouseRead, status_code=status.HTTP_201_CREATED, summary="创建仓库")
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.write"))) -> WarehouseRead:
    """创建仓库主数据。"""

    return service.create_warehouse(db, user, data)


@router.get("/warehouses", response_model=list[WarehouseRead], summary="查询仓库")
def list_warehouses(db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.read"))) -> list[WarehouseRead]:
    """查询启用仓库。"""

    return service.list_warehouses(db, user)


@router.post("/warehouses/{warehouse_id}/locations", response_model=LocationRead, status_code=status.HTTP_201_CREATED, summary="创建库位")
def create_location(warehouse_id: int, data: LocationCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.write"))) -> LocationRead:
    """为仓库创建库位。"""

    return service.create_location(db, user, warehouse_id, data)


@router.get("/warehouses/{warehouse_id}/locations", response_model=list[LocationRead], summary="查询库位")
def list_locations(warehouse_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.read"))) -> list[LocationRead]:
    """查询仓库启用库位。"""

    return service.list_locations(db, warehouse_id, user)


@router.post("/inbounds", response_model=InboundRead, status_code=status.HTTP_201_CREATED, summary="执行库存入库")
def create_inbound(data: InboundCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.write"))) -> InboundRead:
    """将已通过质量验收的到货单写入库存余额和库存流水。"""

    transactions, balances = service.create_inbound(db, user, data)
    return InboundRead(delivery_id=data.delivery_id, transaction_count=len(transactions), transactions=transactions, balances=service.balance_read_models(db, balances))


@router.get("/balances", response_model=InventoryBalancePage, summary="查询库存余额")
def list_balances(product_id: int | None = Query(default=None, gt=0), warehouse_id: int | None = Query(default=None, gt=0), batch_id: int | None = Query(default=None, gt=0), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.read"))) -> InventoryBalancePage:
    """按产品、仓库和批次查询库存余额。"""

    warehouse_ids = service.accessible_warehouse_ids(db, user)
    if warehouse_id is not None and warehouse_ids is not None and warehouse_id not in warehouse_ids:
        raise service.ResourceNotFoundError(f"仓库 {warehouse_id} 不存在")
    items, total = crud.list_balances(db, product_id=product_id, warehouse_id=warehouse_id, batch_id=batch_id, warehouse_ids=warehouse_ids, page=page, page_size=page_size)
    return InventoryBalancePage(items=service.balance_read_models(db, items), total=total, page=page, page_size=page_size)


@router.post("/balances/{balance_id}/freeze", response_model=InventoryBalanceRead, summary="冻结库存余额")
def freeze_balance(balance_id: int, data: InventoryBalanceStatusChange, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.freeze.write"))) -> InventoryBalanceRead:
    """冻结库存余额，不改变库存数量。"""

    balance = service.freeze_balance(db, user, balance_id, data)
    return service.balance_read_models(db, [balance])[0]


@router.post("/balances/{balance_id}/unfreeze", response_model=InventoryBalanceRead, summary="解冻库存余额")
def unfreeze_balance(balance_id: int, data: InventoryBalanceStatusChange, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.freeze.write"))) -> InventoryBalanceRead:
    """解冻库存余额，恢复为可用状态。"""

    balance = service.unfreeze_balance(db, user, balance_id, data)
    return service.balance_read_models(db, [balance])[0]


@router.get("/balances/{balance_id}/status-logs", response_model=InventoryBalanceStatusLogPage, summary="查询库存状态变更记录")
def list_balance_status_logs(balance_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.read"))) -> InventoryBalanceStatusLogPage:
    """查询库存余额冻结和解冻历史。"""

    items, total = service.list_balance_status_logs(db, user, balance_id, page=page, page_size=page_size)
    return InventoryBalanceStatusLogPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/transactions", response_model=InventoryTransactionPage, summary="查询库存流水")
def list_transactions(product_id: int | None = Query(default=None, gt=0), transaction_type: str | None = Query(default=None, pattern="^(INBOUND|OUTBOUND|ADJUSTMENT|TRANSFER_IN|TRANSFER_OUT)$"), page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.read"))) -> InventoryTransactionPage:
    """按产品和流水类型查询库存变化记录。"""

    items, total = crud.list_transactions(db, product_id=product_id, transaction_type=transaction_type, warehouse_ids=service.accessible_warehouse_ids(db, user), page=page, page_size=page_size)
    return InventoryTransactionPage(items=items, total=total, page=page, page_size=page_size)


@router.post("/issue-requests", response_model=InventoryIssueRequestRead, status_code=status.HTTP_201_CREATED, summary="创建库存领用申请")
def create_issue_request(data: InventoryIssueRequestCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.write"))) -> InventoryIssueRequestRead:
    """创建库存领用申请草稿。"""

    return service.create_issue_request(db, user, data)


@router.get("/issue-request-options", response_model=list[InventoryIssueOptionRead], summary="查询可申请领用的库存选项")
def list_issue_request_options(keyword: str | None = Query(default=None, max_length=200),
                               page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=100),
                               db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.read"))) -> list[InventoryIssueOptionRead]:
    """仅返回领用申请所需的可选库存信息。"""

    return service.list_issue_request_options(db, user, keyword=keyword, page=page, page_size=page_size)


@router.get("/issue-requests", response_model=InventoryIssueRequestPage, summary="查询库存领用申请")
def list_issue_requests(
    issue_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED|COMPLETED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.inventory.issue.read")),
) -> InventoryIssueRequestPage:
    """按数据范围分页查询库存领用申请。"""

    items, total = service.list_issue_requests(db, user, status=issue_status, page=page, page_size=page_size)
    return InventoryIssueRequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/issue-requests/{issue_id}", response_model=InventoryIssueRequestRead, summary="查询库存领用申请详情")
def get_issue_request(issue_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.read"))) -> InventoryIssueRequestRead:
    """查询库存领用申请详情。"""

    return service.get_issue_request(db, user, issue_id)


@router.patch("/issue-requests/{issue_id}", response_model=InventoryIssueRequestRead, summary="修改库存领用申请")
def update_issue_request(issue_id: int, data: InventoryIssueRequestUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.write"))) -> InventoryIssueRequestRead:
    """修改草稿或已驳回的库存领用申请。"""

    return service.update_issue_request(db, user, issue_id, data)


@router.post("/issue-requests/{issue_id}/submit", response_model=InventoryIssueRequestRead, summary="提交库存领用申请")
def submit_issue_request(issue_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.write"))) -> InventoryIssueRequestRead:
    """提交库存领用申请审批。"""

    return service.submit_issue_request(db, user, issue_id)


@router.post("/issue-requests/{issue_id}/approve", response_model=InventoryIssueRequestRead, summary="审批库存领用申请")
def approve_issue_request(issue_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.approve"))) -> InventoryIssueRequestRead:
    """审批通过库存领用申请。"""

    return service.approve_issue_request(db, user, issue_id)


@router.post("/issue-requests/{issue_id}/reject", response_model=InventoryIssueRequestRead, summary="驳回库存领用申请")
def reject_issue_request(issue_id: int, data: InventoryIssueReject, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.approve"))) -> InventoryIssueRequestRead:
    """驳回库存领用申请并记录原因。"""

    return service.reject_issue_request(db, user, issue_id, data.reason)


@router.post("/issue-requests/{issue_id}/cancel", response_model=InventoryIssueRequestRead, summary="取消库存领用申请")
def cancel_issue_request(issue_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.write"))) -> InventoryIssueRequestRead:
    """取消草稿或已驳回的库存领用申请。"""

    return service.cancel_issue_request(db, user, issue_id)


@router.post("/issue-requests/{issue_id}/execute", response_model=InventoryIssueRequestRead, summary="执行库存出库")
def execute_issue_request(issue_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.issue.execute"))) -> InventoryIssueRequestRead:
    """锁定库存并执行库存领用出库。"""

    return service.execute_issue_request(db, user, issue_id)


@router.post("/transfer-requests", response_model=InventoryTransferRequestRead, status_code=status.HTTP_201_CREATED, summary="创建库存调拨申请")
def create_transfer_request(data: InventoryTransferRequestCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.write"))) -> InventoryTransferRequestRead:
    """创建库存调拨申请草稿。"""

    return service.create_transfer_request(db, user, data)


@router.get("/transfer-requests", response_model=InventoryTransferRequestPage, summary="查询库存调拨申请")
def list_transfer_requests(
    transfer_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED|COMPLETED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.inventory.transfer.read")),
) -> InventoryTransferRequestPage:
    """按数据范围分页查询库存调拨申请。"""

    items, total = service.list_transfer_requests(db, user, status=transfer_status, page=page, page_size=page_size)
    return InventoryTransferRequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/transfer-requests/{transfer_id}", response_model=InventoryTransferRequestRead, summary="查询库存调拨申请详情")
def get_transfer_request(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.read"))) -> InventoryTransferRequestRead:
    """查询库存调拨申请详情。"""

    return service.get_transfer_request(db, user, transfer_id)


@router.patch("/transfer-requests/{transfer_id}", response_model=InventoryTransferRequestRead, summary="修改库存调拨申请")
def update_transfer_request(transfer_id: int, data: InventoryTransferRequestUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.write"))) -> InventoryTransferRequestRead:
    """修改草稿或已驳回的库存调拨申请。"""

    return service.update_transfer_request(db, user, transfer_id, data)


@router.post("/transfer-requests/{transfer_id}/submit", response_model=InventoryTransferRequestRead, summary="提交库存调拨申请")
def submit_transfer_request(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.write"))) -> InventoryTransferRequestRead:
    """提交库存调拨申请审批。"""

    return service.submit_transfer_request(db, user, transfer_id)


@router.post("/transfer-requests/{transfer_id}/approve", response_model=InventoryTransferRequestRead, summary="审批库存调拨申请")
def approve_transfer_request(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.approve"))) -> InventoryTransferRequestRead:
    """审批通过库存调拨申请。"""

    return service.approve_transfer_request(db, user, transfer_id)


@router.post("/transfer-requests/{transfer_id}/reject", response_model=InventoryTransferRequestRead, summary="驳回库存调拨申请")
def reject_transfer_request(transfer_id: int, data: InventoryTransferReject, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.approve"))) -> InventoryTransferRequestRead:
    """驳回库存调拨申请并记录原因。"""

    return service.reject_transfer_request(db, user, transfer_id, data.reason)


@router.post("/transfer-requests/{transfer_id}/cancel", response_model=InventoryTransferRequestRead, summary="取消库存调拨申请")
def cancel_transfer_request(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.write"))) -> InventoryTransferRequestRead:
    """取消草稿或已驳回的库存调拨申请。"""

    return service.cancel_transfer_request(db, user, transfer_id)


@router.post("/transfer-requests/{transfer_id}/execute", response_model=InventoryTransferRequestRead, summary="执行库存调拨")
def execute_transfer_request(transfer_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.transfer.execute"))) -> InventoryTransferRequestRead:
    """以一个事务完成源库位扣减和目标库位增加。"""

    return service.execute_transfer_request(db, user, transfer_id)


@router.post("/stocktakes", response_model=InventoryStocktakeRequestRead, status_code=status.HTTP_201_CREATED, summary="创建库存盘点申请")
def create_stocktake_request(data: InventoryStocktakeRequestCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.write"))) -> InventoryStocktakeRequestRead:
    """创建库存盘点申请草稿并保存账面数量快照。"""

    return service.create_stocktake_request(db, user, data)


@router.get("/stocktakes", response_model=InventoryStocktakeRequestPage, summary="查询库存盘点申请")
def list_stocktake_requests(
    stocktake_status: str | None = Query(default=None, alias="status", pattern="^(DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED|COMPLETED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.inventory.stocktake.read")),
) -> InventoryStocktakeRequestPage:
    """按数据范围分页查询库存盘点申请。"""

    items, total = service.list_stocktake_requests(db, user, status=stocktake_status, page=page, page_size=page_size)
    return InventoryStocktakeRequestPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stocktakes/{stocktake_id}", response_model=InventoryStocktakeRequestRead, summary="查询库存盘点申请详情")
def get_stocktake_request(stocktake_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.read"))) -> InventoryStocktakeRequestRead:
    """查询库存盘点申请详情。"""

    return service.get_stocktake_request(db, user, stocktake_id)


@router.patch("/stocktakes/{stocktake_id}", response_model=InventoryStocktakeRequestRead, summary="修改库存盘点申请")
def update_stocktake_request(stocktake_id: int, data: InventoryStocktakeRequestUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.write"))) -> InventoryStocktakeRequestRead:
    """修改草稿或已驳回的库存盘点申请。"""

    return service.update_stocktake_request(db, user, stocktake_id, data)


@router.post("/stocktakes/{stocktake_id}/submit", response_model=InventoryStocktakeRequestRead, summary="提交库存盘点申请")
def submit_stocktake_request(stocktake_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.write"))) -> InventoryStocktakeRequestRead:
    """提交库存盘点申请审批。"""

    return service.submit_stocktake_request(db, user, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/approve", response_model=InventoryStocktakeRequestRead, summary="审批库存盘点申请")
def approve_stocktake_request(stocktake_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.approve"))) -> InventoryStocktakeRequestRead:
    """审批通过库存盘点申请。"""

    return service.approve_stocktake_request(db, user, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/reject", response_model=InventoryStocktakeRequestRead, summary="驳回库存盘点申请")
def reject_stocktake_request(stocktake_id: int, data: InventoryStocktakeReject, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.approve"))) -> InventoryStocktakeRequestRead:
    """驳回库存盘点申请并记录原因。"""

    return service.reject_stocktake_request(db, user, stocktake_id, data.reason)


@router.post("/stocktakes/{stocktake_id}/cancel", response_model=InventoryStocktakeRequestRead, summary="取消库存盘点申请")
def cancel_stocktake_request(stocktake_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.write"))) -> InventoryStocktakeRequestRead:
    """取消草稿或已驳回的库存盘点申请。"""

    return service.cancel_stocktake_request(db, user, stocktake_id)


@router.post("/stocktakes/{stocktake_id}/execute", response_model=InventoryStocktakeRequestRead, summary="执行库存盘点")
def execute_stocktake_request(stocktake_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.stocktake.execute"))) -> InventoryStocktakeRequestRead:
    """校验账面快照并执行盘点差异调整。"""

    return service.execute_stocktake_request(db, user, stocktake_id)
