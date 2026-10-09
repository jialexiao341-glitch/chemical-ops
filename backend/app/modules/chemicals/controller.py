"""化学品模块的 HTTP 接口。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_permission
from app.core.db import get_db
from app.modules.chemicals import service
from app.modules.chemicals.schema import ChemicalCreate, ChemicalPage, ChemicalRead, ChemicalUpdate


router = APIRouter(prefix="/chemicals", tags=["化学品管理"])


@router.post("", response_model=ChemicalRead, status_code=status.HTTP_201_CREATED, summary="新增化学品")
def create_chemical(data: ChemicalCreate, db: Session = Depends(get_db), _: object = Depends(require_permission("master.chemicals.write"))) -> ChemicalRead:
    """创建一条化学品主数据记录。"""

    return service.create_chemical(db, data)


@router.get("", response_model=ChemicalPage, summary="分页查询化学品")
def list_chemicals(
    keyword: str | None = Query(default=None, description="按中文名称模糊查询"),
    status: str | None = Query(default=None, pattern="^(ACTIVE|INACTIVE)$", description="按状态筛选"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.chemicals.read")),
) -> ChemicalPage:
    """按名称和状态查询化学品分页列表。"""

    items, total = service.list_chemicals(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )
    return ChemicalPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{chemical_id}", response_model=ChemicalRead, summary="查询化学品详情")
def get_chemical(chemical_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.chemicals.read"))) -> ChemicalRead:
    """根据化学品 ID 查询详情。"""

    return service.get_chemical(db, chemical_id)


@router.patch("/{chemical_id}", response_model=ChemicalRead, summary="更新化学品")
def update_chemical(
    chemical_id: int,
    data: ChemicalUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_permission("master.chemicals.write")),
) -> ChemicalRead:
    """部分更新化学品字段，未传入的字段保持不变。"""

    return service.update_chemical(db, chemical_id, data)


@router.delete("/{chemical_id}", response_model=ChemicalRead, summary="停用化学品")
def delete_chemical(chemical_id: int, db: Session = Depends(get_db), _: object = Depends(require_permission("master.chemicals.delete"))) -> ChemicalRead:
    """软删除化学品，将状态修改为 INACTIVE，不物理删除历史数据。"""

    return service.delete_chemical(db, chemical_id)
