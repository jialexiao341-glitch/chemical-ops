"""后台扫描任务 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.jobs import service
from app.modules.jobs.schema import SchedulerJobRunRead
from app.modules.system.model import User


router = APIRouter(prefix="/jobs", tags=["后台任务"])


@router.post("/overdue-scan", response_model=dict[str, int], summary="扫描逾期到货")
def overdue_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工触发一次逾期到货扫描；生产环境可由定时任务调用同一服务。"""
    return service.scan_overdue_deliveries(db, user)


@router.post("/inventory-expiry-scan", response_model=dict[str, int], summary="扫描临期库存批次")
def inventory_expiry_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工触发一次临期库存扫描。"""

    return service.scan_expiring_inventory(db, user)


@router.post("/alert-scan", response_model=dict[str, int], summary="扫描业务主动提醒")
def alert_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工运行所有已配置的确定性业务提醒规则。"""

    return service.scan_active_alerts(db, user)


@router.get("/runs", response_model=list[SchedulerJobRunRead], summary="查询后台任务运行历史")
def list_job_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("operations.exceptions.read")),
) -> list[SchedulerJobRunRead]:
    """返回最近的后台扫描运行结果，不包含单据正文或个人数据。"""

    return service.list_job_runs(db, limit=limit)
