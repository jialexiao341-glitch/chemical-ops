"""化学品模块的数据持久化操作。

CRUD 函数只负责 SQLAlchemy 数据访问，业务校验放在 service.py。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.chemicals.model import Chemical
from app.modules.chemicals.schema import ChemicalCreate, ChemicalUpdate


def get_by_id(db: Session, chemical_id: int) -> Chemical | None:
    """按主键查询一条化学品，不存在时返回 None。"""

    return db.scalar(select(Chemical).where(Chemical.id == chemical_id))


def get_by_cas_no(db: Session, cas_no: str) -> Chemical | None:
    """按 CAS 号查询化学品。"""

    return db.scalar(select(Chemical).where(Chemical.cas_no == cas_no))


def create(db: Session, data: ChemicalCreate, *, commit: bool = True) -> Chemical:
    """新增化学品并提交事务。"""

    chemical = Chemical(**data.model_dump())
    db.add(chemical)
    if commit:
        db.commit()
        db.refresh(chemical)
    else:
        db.flush()
    return chemical


def list_page(
    db: Session,
    *,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Chemical], int]:
    """按筛选条件返回分页数据和匹配总数。"""

    conditions = []
    if keyword:
        conditions.append(Chemical.chemical_name.like(f"%{keyword}%"))
    if status:
        conditions.append(Chemical.status == status)

    total = db.scalar(select(func.count(Chemical.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Chemical)
            .where(*conditions)
            .order_by(Chemical.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def update(db: Session, chemical: Chemical, data: ChemicalUpdate) -> Chemical:
    """执行部分字段更新并提交事务。"""

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(chemical, field, value)
    db.commit()
    db.refresh(chemical)
    return chemical


def disable(db: Session, chemical: Chemical, *, commit: bool = True) -> Chemical:
    """通过将状态改为 INACTIVE 执行软删除。"""

    chemical.status = "INACTIVE"
    if commit:
        db.commit()
        db.refresh(chemical)
    return chemical
