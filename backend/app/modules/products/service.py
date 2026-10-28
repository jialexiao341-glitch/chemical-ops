"""产品模块的业务服务。"""

from sqlalchemy.orm import Session

from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.modules.products import crud
from app.modules.products.model import Product
from app.modules.products.schema import ProductCreate, ProductUpdate


def get_product(db: Session, product_id: int) -> Product:
    """查询产品详情，不存在时抛出资源不存在异常。"""

    product = crud.get_by_id(db, product_id)
    if product is None:
        raise ResourceNotFoundError(f"产品 {product_id} 不存在")
    return product


def list_products(
    db: Session,
    *,
    keyword: str | None,
    chemical_id: int | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Product], int]:
    """按名称、所属化学品和状态查询产品分页列表。"""

    return crud.list_page(
        db,
        keyword=keyword,
        chemical_id=chemical_id,
        status=status,
        page=page,
        page_size=page_size,
    )


def create_product(db: Session, data: ProductCreate, *, commit: bool = True) -> Product:
    """校验产品编码唯一后创建产品。关联 ID 的存在性由数据库外键保证。"""

    if crud.get_by_code(db, data.product_code):
        raise DuplicateResourceError(f"产品编码 {data.product_code} 已存在")
    return crud.create(db, data, commit=commit)


def update_product(db: Session, product_id: int, data: ProductUpdate) -> Product:
    """校验产品编码不被修改为重复值，并执行产品部分更新。"""

    product = get_product(db, product_id)
    return crud.update(db, product, data)


def delete_product(db: Session, product_id: int) -> Product:
    """以软删除方式停用产品，并保留产品版本变化记录。"""

    return crud.disable(db, get_product(db, product_id))
