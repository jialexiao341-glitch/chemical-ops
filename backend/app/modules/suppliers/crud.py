"""供应商模块的数据持久化操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.suppliers.model import Supplier
from app.modules.suppliers.schema import SupplierCreate, SupplierUpdate


def get_by_id(db: Session, supplier_id: int) -> Supplier | None:
    """按主键查询一条供应商，不存在时返回 None。"""

    return db.scalar(select(Supplier).where(Supplier.id == supplier_id))


def get_by_code(db: Session, supplier_code: str) -> Supplier | None:
    """按企业内部唯一供应商编码查询供应商。"""

    return db.scalar(select(Supplier).where(Supplier.supplier_code == supplier_code))


def create(db: Session, data: SupplierCreate, *, commit: bool = True) -> Supplier:
    """新增供应商并提交事务。"""

    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    if commit:
        db.commit()
        db.refresh(supplier)
    else:
        db.flush()
    return supplier


def list_page(
    db: Session,
    *,
    keyword: str | None,
    region: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Supplier], int]:
    """按筛选条件返回分页数据和匹配总数。"""

    conditions = []
    if keyword:
        conditions.append(Supplier.supplier_name.like(f"%{keyword}%"))
    if region:
        conditions.append(Supplier.region == region)
    if status:
        conditions.append(Supplier.status == status)

    total = db.scalar(select(func.count(Supplier.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Supplier)
            .where(*conditions)
            .order_by(Supplier.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def update(db: Session, supplier: Supplier, data: SupplierUpdate) -> Supplier:
    """执行部分字段更新并提交事务。"""

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    db.commit()
    db.refresh(supplier)
    return supplier


def disable(db: Session, supplier: Supplier, *, commit: bool = True) -> Supplier:
    """通过将状态改为 INACTIVE 执行软删除。"""

    supplier.status = "INACTIVE"
    if commit:
        db.commit()
        db.refresh(supplier)
    return supplier
