"""Dashboard 统计 HTTP 接口。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.dashboard.schema import DashboardOverview, DashboardReport
from app.modules.dashboard.service import get_overview, get_report
from app.modules.system.model import User


router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview", response_model=DashboardOverview, summary="查询运营 Dashboard 概览")
def overview(db: Session = Depends(get_db), _: User = Depends(require_permission("dashboard.read"))) -> DashboardOverview:
    """查询采购、库存、异常和财务核心指标。"""
    return get_overview(db)


@router.get("/report", response_model=DashboardReport, summary="查询 Dashboard 统计报表")
def report(
    date_from: date | None = Query(default=None, description="统计开始日期，包含当天"),
    date_to: date | None = Query(default=None, description="统计结束日期，包含当天"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("dashboard.read")),
) -> DashboardReport:
    """按日期范围聚合订单状态、供应商采购金额和逾期到货数量。"""
    return get_report(db, date_from=date_from, date_to=date_to)
