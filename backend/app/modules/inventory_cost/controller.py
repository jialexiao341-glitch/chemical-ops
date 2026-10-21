"""库存成本、FIFO 出库和有效期预警 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.inventory_cost import service
from app.modules.inventory_cost.schema import ExpiryAlertRead, FifoAllocationRead, FifoOutboundCreate, FifoOutboundRead
from app.modules.system.model import User


router = APIRouter(prefix="/inventory", tags=["库存成本"])


@router.post("/fifo-outbounds", response_model=FifoOutboundRead, status_code=201, summary="执行 FIFO 库存出库")
def create_fifo_outbound(data: FifoOutboundCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.cost.write"))) -> FifoOutboundRead:
    """按最早入库成本层出库，request_no 重复提交返回原结果。"""
    result = FifoOutboundRead.model_validate(service.create_fifo_outbound(db, user, data))
    from app.modules.system.crud import get_user_permission_codes
    if "warehouse.inventory.cost.read" not in get_user_permission_codes(db, user.id):
        result.total_cost = None
        for allocation in result.allocations:
            allocation.unit_cost = None
            allocation.total_cost = None
    return result


@router.get("/expiry-alerts", response_model=list[ExpiryAlertRead], summary="查询库存有效期预警")
def list_expiry_alerts(days: int = Query(default=30, ge=0, le=3650),
                       page: int = Query(default=1, ge=1), page_size: int = Query(default=100, ge=1, le=100),
                       db: Session = Depends(get_db), user: User = Depends(require_permission("warehouse.inventory.expiry.read"))) -> list[ExpiryAlertRead]:
    """查询未来指定天数内到期且仍有库存的批次。"""
    from app.modules.inventory.service import accessible_warehouse_ids
    rows = service.list_expiry_alerts(db, days=days, warehouse_ids=accessible_warehouse_ids(db, user), page=page, page_size=page_size)
    return [ExpiryAlertRead(product_id=batch.product_id, batch_id=batch.id, batch_no=batch.batch_no, warehouse_id=balance.warehouse_id, location_id=balance.location_id, quantity=balance.quantity, expiry_date=batch.expiry_date, days_remaining=days_remaining, alert_level=level) for batch, balance, days_remaining, level in rows]
