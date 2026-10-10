"""采购运营异常的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.core.errors import ResourceNotFoundError
from app.modules.operation_exceptions import service
from app.modules.operation_exceptions.schema import (
    OperationExceptionCreate,
    OperationExceptionAssigneeRead,
    OperationExceptionPage,
    OperationExceptionRead,
    OperationExceptionUpdate,
    OperationTaskCommentCreate,
    OperationTaskCommentPage,
    OperationTaskCommentRead,
    OperationTaskCreate,
    OperationTaskPage,
    OperationTaskRead,
    OperationTaskUpdate,
)
from app.modules.system.model import User


router = APIRouter(prefix="/operation-exceptions", tags=["运营异常"])


@router.get("/assignees", response_model=list[OperationExceptionAssigneeRead], summary="查询异常经办人选项")
def list_assignee_options(db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.read"))) -> list[User]:
    """按当前部门范围返回经办候选人的最小字段。"""

    return service.list_assignee_options(db, user)


@router.post("", response_model=OperationExceptionRead, status_code=status.HTTP_201_CREATED, summary="登记运营异常")
def create_exception(data: OperationExceptionCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> OperationExceptionRead:
    """登记短交、质量、文件、逾期或其他运营异常。"""

    return service.create_exception(db, user, data)


@router.get("", response_model=OperationExceptionPage, summary="分页查询运营异常")
def list_exceptions(
    exception_type: str | None = Query(default=None, pattern="^(SHORT_DELIVERY|QUALITY|QUALITY_PENDING|LOW_STOCK|DOCUMENT|OVERDUE|INVENTORY_EXPIRY|OTHER)$"),
    exception_status: str | None = Query(default=None, alias="status", pattern="^(OPEN|PROCESSING|RESOLVED|CLOSED|CANCELLED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("operations.exceptions.read")),
) -> OperationExceptionPage:
    """按用户数据范围分页查询运营异常。"""

    items, total = service.list_exceptions(db, user, exception_type=exception_type, status=exception_status, page=page, page_size=page_size)
    return OperationExceptionPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{exception_id}", response_model=OperationExceptionRead, summary="查询运营异常详情")
def get_exception(exception_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.read"))) -> OperationExceptionRead:
    """查询运营异常详情。"""

    return service.get_exception(db, user, exception_id)


@router.patch("/{exception_id}", response_model=OperationExceptionRead, summary="更新运营异常")
def update_exception(exception_id: int, data: OperationExceptionUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> OperationExceptionRead:
    """指派异常负责人并推进处理状态。"""

    return service.update_exception(db, user, exception_id, data)


@router.post("/{exception_id}/tasks", response_model=OperationTaskRead, status_code=status.HTTP_201_CREATED, summary="创建异常处理任务")
def create_task(exception_id: int, data: OperationTaskCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> OperationTaskRead:
    """为运营异常创建处理任务。"""

    return service.create_task(db, user, exception_id, data)


@router.get("/{exception_id}/tasks", response_model=OperationTaskPage, summary="查询异常处理任务")
def list_tasks(
    exception_id: int,
    task_status: str | None = Query(default=None, alias="status", pattern="^(OPEN|PROCESSING|COMPLETED|CANCELLED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("operations.exceptions.read")),
) -> OperationTaskPage:
    """按异常分页查询处理任务。"""

    items, total = service.list_tasks(db, user, exception_id, status=task_status, page=page, page_size=page_size)
    return OperationTaskPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{exception_id}/tasks/{task_id}", response_model=OperationTaskRead, summary="查询异常任务详情")
def get_task(exception_id: int, task_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.read"))) -> OperationTaskRead:
    """查询指定异常下的任务详情。"""

    task = service.get_task(db, user, task_id)
    if task.exception_id != exception_id:
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    return task


@router.patch("/{exception_id}/tasks/{task_id}", response_model=OperationTaskRead, summary="更新异常处理任务")
def update_task(exception_id: int, task_id: int, data: OperationTaskUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> OperationTaskRead:
    """更新任务负责人、优先级、截止时间或状态。"""

    task = service.get_task(db, user, task_id)
    if task.exception_id != exception_id:
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    return service.update_task(db, user, task_id, data)


@router.post("/{exception_id}/tasks/{task_id}/comments", response_model=OperationTaskCommentRead, status_code=status.HTTP_201_CREATED, summary="追加任务处理记录")
def create_comment(exception_id: int, task_id: int, data: OperationTaskCommentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("operations.exceptions.write"))) -> OperationTaskCommentRead:
    """为异常任务追加处理记录。"""

    task = service.get_task(db, user, task_id)
    if task.exception_id != exception_id:
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    return service.create_comment(db, user, task_id, data)


@router.get("/{exception_id}/tasks/{task_id}/comments", response_model=OperationTaskCommentPage, summary="查询任务处理记录")
def list_comments(
    exception_id: int,
    task_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("operations.exceptions.read")),
) -> OperationTaskCommentPage:
    """分页查询异常任务的处理记录。"""

    task = service.get_task(db, user, task_id)
    if task.exception_id != exception_id:
        raise ResourceNotFoundError(f"异常任务 {task_id} 不存在")
    items, total = service.list_comments(db, user, task_id, page=page, page_size=page_size)
    return OperationTaskCommentPage(items=items, total=total, page=page, page_size=page_size)
