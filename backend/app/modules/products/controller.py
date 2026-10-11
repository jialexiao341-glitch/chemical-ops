"""产品模块的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from pydantic import TypeAdapter

from app.core.auth import get_current_user, require_permission
from app.core.db import get_db
from app.core.cache import cached
from app.core.config import get_settings
from app.modules.products import crud, service
from app.modules.products.schema import ProductCreate, ProductPage, ProductRead, ProductUpdate, UnitRead
from app.modules.quality_acceptances import standards
from app.modules.quality_acceptances.schema import QualityStandardCreate, QualityStandardRead
from app.modules.system.model import User


router = APIRouter(prefix="/products", tags=["产品管理"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED, summary="新增产品")
def create_product(data: ProductCreate, db: Session = Depends(get_db), _: object = Depends(require_permission("master.products.write"))) -> ProductRead:
    """创建一条产品规格记录。"""

    return service.create_product(db, data)


@router.get("", response_model=ProductPage, summary="分页查询产品")
def list_products(
    keyword: str | None = Query(default=None, description="按产品名称模糊查询"),
    chemical_id: int | None = Query(default=None, gt=0, description="按所属化学品筛选"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|INACTIVE|PENDING_CONFIRMATION)$", description="按状态筛选"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.products.read")),
) -> ProductPage:
    """按名称、所属化学品和状态查询产品分页列表。"""

    items, total = service.list_products(
        db,
        keyword=keyword,
        chemical_id=chemical_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ProductPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/units", response_model=list[UnitRead], summary="查询计量单位")
def list_units(db: Session = Depends(get_db), _: User = Depends(require_permission("master.products.read"))) -> list[UnitRead]:
    """返回计量单位字典，避免前端直接使用单位 ID 或写死单位名称。"""

    return crud.list_units(db)


@router.get("/{product_id}", response_model=ProductRead, summary="查询产品详情")
def get_product(product_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.products.read"))) -> ProductRead:
    """根据产品 ID 查询详情。"""

    return cached(db, "product_catalog", ("detail", product_id), TypeAdapter(ProductRead),
                  lambda: ProductRead.model_validate(service.get_product(db, product_id)),
                  ttl=get_settings().redis_cache_ttl_seconds)


@router.get("/{product_id}/quality-standards", response_model=list[QualityStandardRead], summary="查询产品检测标准版本")
def list_quality_standards(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("master.products.read")),
) -> list[QualityStandardRead]:
    """向有产品读取权限的用户返回指定产品的检测标准版本。"""
    return standards.list_standards(db, product_id)


@router.post("/{product_id}/quality-standards", response_model=QualityStandardRead, status_code=201, summary="创建产品检测标准版本")
def create_quality_standard(
    product_id: int,
    data: QualityStandardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("master.products.write")),
) -> QualityStandardRead:
    """由有产品写入权限的用户为产品创建检测标准新版本。"""
    return standards.create_standard(db, user, product_id, data)


@router.patch("/{product_id}", response_model=ProductRead, summary="更新产品")
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.products.write")),
) -> ProductRead:
    """部分更新产品字段，并递增产品版本号。"""

    return service.update_product(db, product_id, data)


@router.delete("/{product_id}", response_model=ProductRead, summary="停用产品")
def delete_product(product_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.products.delete"))) -> ProductRead:
    """软删除产品，将状态修改为 INACTIVE。"""

    return service.delete_product(db, product_id)
