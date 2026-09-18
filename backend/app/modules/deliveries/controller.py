"""到货和收货确认的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.deliveries import service
from app.modules.deliveries.schema import DeliveryCreate, DeliveryPage, DeliveryRead, DeliveryReceive
from app.modules.system.model import User


router = APIRouter(prefix="/deliveries", tags=["到货收货"])


@router.post("", response_model=DeliveryRead, status_code=status.HTTP_201_CREATED, summary="登记到货计划")
def create_delivery(
    data: DeliveryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.deliveries.write")),
) -> DeliveryRead:
    """为已下单采购订单登记到货计划。"""

    return service.create_delivery(db, user, data)


@router.get("", response_model=DeliveryPage, summary="分页查询到货单")
def list_deliveries(
    keyword: str | None = Query(default=None, description="按到货单编号查询"),
    delivery_status: str | None = Query(default=None, alias="status", description="到货状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.deliveries.read")),
) -> DeliveryPage:
    """按用户数据范围分页查询到货单。"""

    items, total = service.list_deliveries(db, user, keyword=keyword, status=delivery_status, page=page, page_size=page_size)
    return DeliveryPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{delivery_id}", response_model=DeliveryRead, summary="查询到货单详情")
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.deliveries.read")),
) -> DeliveryRead:
    """查询到货单和到货明细。"""

    return service.get_delivery(db, user, delivery_id)


@router.post("/{delivery_id}/receive", response_model=DeliveryRead, summary="确认收货")
def receive_delivery(
    delivery_id: int,
    data: DeliveryReceive,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("warehouse.deliveries.write")),
) -> DeliveryRead:
    """确认实际到货数量，并更新采购订单收货状态。"""

    return service.receive_delivery(db, user, delivery_id, data)
