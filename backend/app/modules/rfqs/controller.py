"""询价与供应商报价的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.rfqs import service
from app.modules.rfqs.schema import (
    QuoteComparisonRead,
    QuoteSelection,
    RFQCreate,
    RFQPage,
    RFQRead,
    RFQUpdate,
    SupplierQuoteCreate,
)
from app.modules.system.model import User


router = APIRouter(prefix="/rfqs", tags=["询价与报价"])


@router.post("", response_model=RFQRead, status_code=status.HTTP_201_CREATED, summary="创建询价单")
def create_rfq(
    data: RFQCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.write")),
) -> RFQRead:
    """创建询价草稿，并关联采购申请明细和邀请供应商。"""

    return service.create_rfq(db, user, data)


@router.get("", response_model=RFQPage, summary="分页查询询价单")
def list_rfqs(
    keyword: str | None = Query(default=None, description="按询价编号查询"),
    rfq_status: str | None = Query(default=None, alias="status", description="询价状态"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.read")),
) -> RFQPage:
    """按用户数据范围分页查询询价单。"""

    items, total = service.list_rfqs(db, user, keyword=keyword, status=rfq_status, page=page, page_size=page_size)
    return RFQPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{rfq_id}", response_model=RFQRead, summary="查询询价详情")
def get_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.read")),
) -> RFQRead:
    """查询询价明细、供应商响应、报价和比价记录。"""

    return service.get_rfq(db, user, rfq_id)


@router.patch("/{rfq_id}", response_model=RFQRead, summary="更新询价草稿")
def update_rfq(
    rfq_id: int,
    data: RFQUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.write")),
) -> RFQRead:
    """更新草稿状态的询价信息。"""

    return service.update_rfq(db, user, rfq_id, data)


@router.post("/{rfq_id}/send", response_model=RFQRead, summary="发送询价单")
def send_rfq(
    rfq_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.write")),
) -> RFQRead:
    """发送询价单并通知后续报价流程开始。"""

    return service.send_rfq(db, user, rfq_id)


@router.post("/{rfq_id}/quotes", response_model=RFQRead, summary="录入供应商报价")
def create_quote(
    rfq_id: int,
    data: SupplierQuoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.quote")),
) -> RFQRead:
    """录入供应商报价明细并更新供应商响应状态。"""

    return service.create_quote(db, user, rfq_id, data)


@router.post("/{rfq_id}/comparison", response_model=QuoteComparisonRead, summary="生成报价比较")
def build_comparison(
    rfq_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.compare")),
) -> QuoteComparisonRead:
    """按报价明细单价生成比价快照。"""

    return service.build_comparison(db, user, rfq_id)


@router.get("/{rfq_id}/comparison", response_model=QuoteComparisonRead, summary="查询报价比较")
def get_comparison(
    rfq_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.read")),
) -> QuoteComparisonRead:
    """查询当前询价单最近一次生成的比价结果。"""

    return service.get_latest_comparison(db, user, rfq_id)


@router.post("/{rfq_id}/select-quote", response_model=RFQRead, summary="确认中选报价")
def select_quote(
    rfq_id: int,
    data: QuoteSelection,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.rfqs.award")),
) -> RFQRead:
    """确认中选报价并关闭询价单。"""

    return service.select_quote(db, user, rfq_id, data)
