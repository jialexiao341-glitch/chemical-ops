"""产品模块的数据持久化操作。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.products.schema import ProductCreate, ProductUpdate


def get_by_id(db: Session, product_id: int) -> Product | None:
    """按主键查询一条产品，不存在时返回 None。"""

    return db.scalar(select(Product).where(Product.id == product_id))


def get_by_code(db: Session, product_code: str) -> Product | None:
    """按企业内部唯一产品编码查询产品。"""

    return db.scalar(select(Product).where(Product.product_code == product_code))


def list_units(db: Session) -> list[Unit]:
    """查询计量单位字典，供所有业务页面显示统一单位名称。"""

    return list(db.scalars(select(Unit).order_by(Unit.id)).all())


def create(db: Session, data: ProductCreate) -> Product:
    """新增产品并提交事务。"""

    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def list_page(
    db: Session,
    *,
    keyword: str | None,
    chemical_id: int | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Product], int]:
    """按筛选条件返回分页数据和匹配总数。"""

    conditions = []
    if keyword:
        conditions.append(Product.product_name.like(f"%{keyword}%"))
    if chemical_id:
        conditions.append(Product.chemical_id == chemical_id)
    if status:
        conditions.append(Product.status == status)

    total = db.scalar(select(func.count(Product.id)).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(Product)
            .where(*conditions)
            .order_by(Product.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def update(db: Session, product: Product, data: ProductUpdate) -> Product:
    """执行部分字段更新，并递增产品资料版本号。"""

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    product.version_no += 1
    db.commit()
    db.refresh(product)
    return product


def disable(db: Session, product: Product) -> Product:
    """通过将状态改为 INACTIVE 执行软删除。"""

    product.status = "INACTIVE"
    product.version_no += 1
    db.commit()
    db.refresh(product)
    return product
