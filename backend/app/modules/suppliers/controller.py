"""供应商模块的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.suppliers import service
from app.modules.suppliers.schema import SupplierCreate, SupplierPage, SupplierRead, SupplierUpdate


router = APIRouter(prefix="/suppliers", tags=["供应商管理"])


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED, summary="新增供应商")
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db), _: object = Depends(require_permission("master.suppliers.write"))) -> SupplierRead:
    """创建一条供应商主档案。"""

    return service.create_supplier(db, data)


@router.get("", response_model=SupplierPage, summary="分页查询供应商")
def list_suppliers(
    keyword: str | None = Query(default=None, description="按供应商名称模糊查询"),
    region: str | None = Query(default=None, description="按地区精确筛选"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|SUSPENDED|INACTIVE)$", description="按状态筛选"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.suppliers.read")),
) -> SupplierPage:
    """按名称、地区和状态查询供应商分页列表。"""

    items, total = service.list_suppliers(
        db,
        keyword=keyword,
        region=region,
        status=status,
        page=page,
        page_size=page_size,
    )
    return SupplierPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{supplier_id}", response_model=SupplierRead, summary="查询供应商详情")
def get_supplier(supplier_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.suppliers.read"))) -> SupplierRead:
    """根据供应商 ID 查询详情。"""

    return service.get_supplier(db, supplier_id)


@router.patch("/{supplier_id}", response_model=SupplierRead, summary="更新供应商")
def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.suppliers.write")),
) -> SupplierRead:
    """部分更新供应商字段，未传入的字段保持不变。"""

    return service.update_supplier(db, supplier_id, data)


@router.delete("/{supplier_id}", response_model=SupplierRead, summary="停用供应商")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.suppliers.write"))) -> SupplierRead:
    """软删除供应商，将状态修改为 INACTIVE，不物理删除采购历史。"""

    return service.delete_supplier(db, supplier_id)
