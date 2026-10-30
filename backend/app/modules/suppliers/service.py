"""供应商模块的业务服务。"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.cache import invalidate as bump_namespace
from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.modules.suppliers import crud
from app.modules.suppliers.model import Supplier
from app.modules.suppliers.schema import SupplierCreate, SupplierUpdate


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    """查询供应商详情，不存在时抛出资源不存在异常。"""

    supplier = crud.get_by_id(db, supplier_id)
    if supplier is None:
        raise ResourceNotFoundError(f"供应商 {supplier_id} 不存在")
    return supplier


def get_supplier_by_code(db: Session, supplier_code: str) -> Supplier | None:
    """按准确供应商编码读取主数据记录。"""

    return crud.get_by_code(db, supplier_code)


def list_suppliers(
    db: Session,
    *,
    keyword: str | None,
    region: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Supplier], int]:
    """按名称、地区和状态查询供应商分页列表。"""

    return crud.list_page(
        db,
        keyword=keyword,
        region=region,
        status=status,
        page=page,
        page_size=page_size,
    )


def create_supplier(db: Session, data: SupplierCreate, *, commit: bool = True) -> Supplier:
    """校验供应商编码唯一后创建供应商。"""

    if data.unified_credit_code is not None and not data.unified_credit_code.strip():
        data.unified_credit_code = None
    if crud.get_by_code(db, data.supplier_code):
        raise DuplicateResourceError(f"供应商编码 {data.supplier_code} 已存在")
    try:
        supplier = crud.create(db, data, commit=commit)
    except IntegrityError:
        if commit:
            db.rollback()
        raise DuplicateResourceError("供应商编码或统一社会信用代码已存在") from None
    if commit:
        bump_namespace("supplier_directory")
    return supplier


def update_supplier(db: Session, supplier_id: int, data: SupplierUpdate) -> Supplier:
    """执行供应商部分更新；供应商编码作为不可变业务标识。"""

    if data.unified_credit_code is not None and not data.unified_credit_code.strip():
        data.unified_credit_code = None
    try:
        updated = crud.update(db, get_supplier(db, supplier_id), data)
    except IntegrityError:
        db.rollback()
        raise DuplicateResourceError("统一社会信用代码已被其他供应商使用") from None
    bump_namespace("supplier_directory")
    return updated


def delete_supplier(db: Session, supplier_id: int) -> Supplier:
    """以软删除方式停用供应商，保留采购历史数据。"""

    disabled = crud.disable(db, get_supplier(db, supplier_id))
    bump_namespace("supplier_directory")
    return disabled
