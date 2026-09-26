"""列表批量停用、草稿删除、选中导出及主数据 CSV 导入。"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.chemicals.model import Chemical
from app.modules.chemicals.schema import ChemicalCreate
from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.inventory.model import (
    InventoryBalance, InventoryIssueRequest, InventoryStocktakeRequest,
    InventoryTransaction, InventoryTransferRequest,
)
from app.modules.operation_exceptions.model import OperationException
from app.modules.products.model import Product
from app.modules.products.schema import ProductCreate
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.rfqs.model import RFQ
from app.modules.suppliers.model import Supplier
from app.modules.suppliers.schema import SupplierCreate
from app.modules.system import crud as system_crud
from app.modules.system.model import Department, Permission, Role, RolePermission, User


router = APIRouter(prefix="/batch", tags=["批量数据操作"])


@dataclass(frozen=True)
class Resource:
    model: type
    read_permission: str
    write_permission: str | None = None
    delete_mode: str = "readonly"  # master / draft / permission / readonly


RESOURCES: dict[str, Resource] = {
    "master.chemicals": Resource(Chemical, "master.chemicals.read", "master.chemicals.write", "master"),
    "master.products": Resource(Product, "master.products.read", "master.products.write", "master"),
    "master.suppliers": Resource(Supplier, "master.suppliers.read", "master.suppliers.write", "master"),
    "system.users": Resource(User, "system.users.read", "system.users.write", "master"),
    "system.departments": Resource(Department, "system.departments.read", "system.departments.write", "master"),
    "system.roles": Resource(Role, "system.roles.read", "system.roles.write", "master"),
    "system.permissions": Resource(Permission, "system.permissions.read", "system.permissions.write", "permission"),
    "procurement.requests": Resource(PurchaseRequest, "procurement.requests.read", "procurement.requests.write", "draft"),
    "procurement.rfqs": Resource(RFQ, "procurement.rfqs.read", "procurement.rfqs.write", "draft"),
    "procurement.orders": Resource(PurchaseOrder, "procurement.orders.read", "procurement.orders.write", "draft"),
    "warehouse.deliveries": Resource(Delivery, "warehouse.deliveries.read", "warehouse.deliveries.write"),
    "warehouse.inventory.balances": Resource(InventoryBalance, "warehouse.inventory.read"),
    "warehouse.inventory.transactions": Resource(InventoryTransaction, "warehouse.inventory.read"),
    "warehouse.inventory.issues": Resource(InventoryIssueRequest, "warehouse.inventory.issue.read", "warehouse.inventory.issue.write", "draft"),
    "warehouse.inventory.transfers": Resource(InventoryTransferRequest, "warehouse.inventory.transfer.read", "warehouse.inventory.transfer.write", "draft"),
    "warehouse.inventory.stocktakes": Resource(InventoryStocktakeRequest, "warehouse.inventory.stocktake.read", "warehouse.inventory.stocktake.write", "draft"),
    "quality.acceptances": Resource(QualityAcceptance, "quality.acceptances.read"),
    "finance.reconciliations": Resource(FinanceReconciliation, "finance.reconciliations.read", "finance.reconciliations.write", "draft"),
    "finance.invoices": Resource(FinanceInvoice, "finance.invoices.read", "finance.invoices.write", "draft"),
    "finance.payments": Resource(FinancePayment, "finance.payments.read"),
    "finance.settlements": Resource(FinanceSettlement, "finance.settlements.read", "finance.settlements.write", "draft"),
    "operations.exceptions": Resource(OperationException, "operations.exceptions.read"),
}


class Selection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


def _resource(name: str) -> Resource:
    spec = RESOURCES.get(name)
    if spec is None:
        raise ResourceNotFoundError(f"不支持的功能区：{name}")
    return spec


def _authorize(db: Session, user: User, permission: str | None) -> None:
    if permission is None:
        raise HTTPException(status_code=403, detail="该功能区不支持此操作")
    if "SYS_ADMIN" in system_crud.get_user_role_codes(db, user.id):
        return
    if permission not in system_crud.get_user_permission_codes(db, user.id):
        raise HTTPException(status_code=403, detail="没有执行该操作的权限")


def _rows(db: Session, spec: Resource, ids: list[int]) -> list:
    unique_ids = sorted(set(ids))
    rows = list(db.scalars(select(spec.model).where(spec.model.id.in_(unique_ids)).order_by(spec.model.id)).all())
    found = {row.id for row in rows}
    missing = set(unique_ids) - found
    if missing:
        raise ResourceNotFoundError(f"所选记录不存在：{sorted(missing)}")
    return rows


@router.post("/{name}/delete", summary="批量停用主数据或删除草稿")
def batch_delete(name: str, selection: Selection, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int | str]:
    spec = _resource(name)
    _authorize(db, user, spec.write_permission)
    if spec.delete_mode == "readonly":
        raise BusinessValidationError("已生效记录和流水不可删除")
    if len(set(selection.ids)) != len(selection.ids):
        raise BusinessValidationError("所选记录包含重复 ID")

    rows = _rows(db, spec, selection.ids)
    if spec.delete_mode == "draft" and any(row.status != "DRAFT" for row in rows):
        raise BusinessValidationError("只能批量删除草稿；请取消选择已提交或已生效记录")
    if spec.delete_mode == "master" and name == "system.users" and user.id in selection.ids:
        raise BusinessValidationError("不能停用当前登录账号")
    if spec.delete_mode == "permission":
        used = db.scalar(select(RolePermission.permission_id).where(RolePermission.permission_id.in_(selection.ids)).limit(1))
        if used is not None:
            raise BusinessValidationError("所选权限仍被角色引用，不能删除")

    try:
        for row in rows:
            if spec.delete_mode == "master":
                row.status = "INACTIVE"
                if name == "master.products":
                    row.version_no += 1
                if name == "system.users":
                    row.token_version += 1
            else:
                db.delete(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BusinessValidationError("所选记录存在业务引用，无法批量删除") from None
    return {"count": len(rows), "action": "disabled" if spec.delete_mode == "master" else "deleted"}


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False)
    text = str(value)
    # 防止 Excel 将外部数据解释为公式。
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@router.post("/{name}/export", summary="将选中记录导出为 CSV")
def batch_export(name: str, selection: Selection, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    spec = _resource(name)
    _authorize(db, user, spec.read_permission)
    rows = _rows(db, spec, selection.ids)
    excluded = {"password_hash", "token_version", "avatar", "avatar_base64"}
    columns = [column.key for column in spec.model.__table__.columns if column.key not in excluded and not isinstance(getattr(rows[0], column.key), bytes)]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_value(getattr(row, column)) for column in columns])
    filename = name.replace(".", "-") + ".csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


IMPORT_MODELS = {
    "master.chemicals": (Chemical, ChemicalCreate),
    "master.products": (Product, ProductCreate),
    "master.suppliers": (Supplier, SupplierCreate),
}


@router.post("/{name}/import", summary="导入主数据 CSV")
async def batch_import(name: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:
    spec = _resource(name)
    _authorize(db, user, spec.write_permission)
    if name not in IMPORT_MODELS:
        raise BusinessValidationError("该功能区暂不支持导入")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise BusinessValidationError("请上传 CSV 文件")
    content = await file.read(2_000_001)
    if len(content) > 2_000_000:
        raise BusinessValidationError("CSV 文件不能超过 2MB")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not reader.fieldnames:
            raise BusinessValidationError("CSV 缺少表头")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise BusinessValidationError("CSV 表头包含重复字段")
        model, schema = IMPORT_MODELS[name]
        allowed = set(schema.model_fields)
        if set(reader.fieldnames) - allowed:
            raise BusinessValidationError("CSV 包含不支持的字段")
        records = list(reader)
        if not records or len(records) > 500:
            raise BusinessValidationError("每次需导入 1 至 500 行")
        validated = []
        for line_no, record in enumerate(records, start=2):
            if None in record:
                raise BusinessValidationError(f"第 {line_no} 行列数与表头不一致")
            try:
                values = schema.model_validate({key: value for key, value in record.items() if value not in ("", None)}).model_dump()
            except ValidationError as exc:
                raise BusinessValidationError(f"第 {line_no} 行字段校验失败：{exc.errors()[0]['loc']}") from None
            validated.append(values)
        for values in validated:
            db.add(model(**values))
        db.commit()
    except UnicodeDecodeError:
        raise BusinessValidationError("CSV 请使用 UTF-8 编码") from None
    except IntegrityError:
        db.rollback()
        raise BusinessValidationError("导入数据存在重复编码或无效关联 ID，整批未保存") from None
    return {"count": len(records)}
