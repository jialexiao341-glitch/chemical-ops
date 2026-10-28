"""化学品模块的业务服务。"""

from sqlalchemy.orm import Session

from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.modules.chemicals import crud
from app.modules.chemicals.model import Chemical
from app.modules.chemicals.schema import ChemicalCreate, ChemicalUpdate


def get_chemical(db: Session, chemical_id: int) -> Chemical:
    """查询化学品详情，不存在时抛出资源不存在异常。"""

    chemical = crud.get_by_id(db, chemical_id)
    if chemical is None:
        raise ResourceNotFoundError(f"化学品 {chemical_id} 不存在")
    return chemical


def list_chemicals(
    db: Session,
    *,
    keyword: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Chemical], int]:
    """按名称和状态查询化学品分页列表。"""

    return crud.list_page(
        db,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )


def create_chemical(db: Session, data: ChemicalCreate, *, commit: bool = True) -> Chemical:
    """校验唯一 CAS 号后创建化学品。"""

    if data.cas_no and crud.get_by_cas_no(db, data.cas_no):
        raise DuplicateResourceError(f"CAS 号 {data.cas_no} 已存在")
    return crud.create(db, data, commit=commit)


def update_chemical(db: Session, chemical_id: int, data: ChemicalUpdate) -> Chemical:
    """校验更新后的 CAS 号并执行部分更新。"""

    chemical = get_chemical(db, chemical_id)
    if "cas_no" in data.model_fields_set and data.cas_no:
        duplicate = crud.get_by_cas_no(db, data.cas_no)
        if duplicate and duplicate.id != chemical_id:
            raise DuplicateResourceError(f"CAS 号 {data.cas_no} 已存在")
    return crud.update(db, chemical, data)


def delete_chemical(db: Session, chemical_id: int) -> Chemical:
    """以软删除方式停用化学品，保留历史业务引用。"""

    return crud.disable(db, get_chemical(db, chemical_id))
