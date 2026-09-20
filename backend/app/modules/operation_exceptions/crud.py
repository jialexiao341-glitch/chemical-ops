"""异常管理模块的数据访问操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.operation_exceptions.model import OperationException, OperationTask, OperationTaskComment


def get_by_id(db: Session, exception_id: int, *, for_update: bool = False) -> OperationException | None:
    """按主键查询异常。"""

    statement = select(OperationException).where(OperationException.id == exception_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_page(db: Session, *, owner_id: int | None, exception_type: str | None, status: str | None, page: int, page_size: int) -> tuple[list[OperationException], int]:
    """按数据范围和筛选条件分页查询异常。"""

    conditions = []
    if owner_id is not None:
        conditions.append(OperationException.owner_id == owner_id)
    if exception_type:
        conditions.append(OperationException.exception_type == exception_type)
    if status:
        conditions.append(OperationException.status == status)
    total = db.scalar(select(func.count(OperationException.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(OperationException).where(*conditions).order_by(OperationException.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return items, total


def get_task(db: Session, task_id: int, *, for_update: bool = False) -> OperationTask | None:
    """按主键查询异常处理任务。"""

    statement = select(OperationTask).where(OperationTask.id == task_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def list_tasks(db: Session, *, exception_id: int, status: str | None, page: int, page_size: int) -> tuple[list[OperationTask], int]:
    """按异常和任务状态分页查询处理任务。"""

    conditions = [OperationTask.exception_id == exception_id]
    if status:
        conditions.append(OperationTask.status == status)
    total = db.scalar(select(func.count(OperationTask.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(OperationTask)
            .where(*conditions)
            .order_by(OperationTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_comment(db: Session, comment_id: int) -> OperationTaskComment | None:
    """按主键查询任务处理记录。"""

    return db.get(OperationTaskComment, comment_id)


def list_comments(db: Session, *, task_id: int, page: int, page_size: int) -> tuple[list[OperationTaskComment], int]:
    """按任务分页查询处理记录。"""

    conditions = [OperationTaskComment.task_id == task_id]
    total = db.scalar(select(func.count(OperationTaskComment.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(OperationTaskComment)
            .where(*conditions)
            .order_by(OperationTaskComment.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total
