"""后台扫描任务 HTTP 接口。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.jobs import service
from app.modules.system.model import User


router = APIRouter(prefix="/jobs", tags=["后台任务"])


@router.post("/overdue-scan", response_model=dict[str, int], summary="扫描逾期到货")
def overdue_scan(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> dict[str, int]:
    """手工触发一次逾期到货扫描；生产环境可由定时任务调用同一服务。"""
    return service.scan_overdue_deliveries(db, user)
