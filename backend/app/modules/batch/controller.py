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
from app.modules.system.audit import add_audit_log
from app.modules.system.model import Department, Permission, Role, RolePermission, User


router = APIRouter(prefix="/batch", tags=["批量数据操作"])


@dataclass(frozen=True)
class Resource:
    model: type
    read_permission: str
    write_permission: str | None = None
    delete_mode: str = "readonly"  # master / draft / permission / readonly
    delete_permission: str | None = None


RESOURCES: dict[str, Resource] = {
    "master.chemicals": Resource(Chemical, "master.chemicals.read", "master.chemicals.write", "master", "master.chemicals.delete"),
    "master.products": Resource(Product, "master.products.read", "master.products.write", "master", "master.products.delete"),
    "master.suppliers": Resource(Supplier, "master.suppliers.read", "master.suppliers.write", "master", "master.suppliers.deactivate"),
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


def _rows(db: Session, spec: Resource, ids: list[int], *, for_update: bool = False) -> list:
    unique_ids = sorted(set(ids))
    statement = select(spec.model).where(spec.model.id.in_(unique_ids)).order_by(spec.model.id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    rows = list(db.scalars(statement).all())
    found = {row.id for row in rows}
    missing = set(unique_ids) - found
    if missing:
        raise ResourceNotFoundError(f"所选记录不存在：{sorted(missing)}")
    return rows


def _authorize_row_scope(db: Session, user: User, name: str, rows: list, *, write: bool = False) -> None:
    """复用业务详情查询的数据范围，防止批量接口通过猜测 ID 越权。"""
    if name == "procurement.requests":
        from app.modules.purchase_requests.service import get_request, get_request_for_write
        for row in rows:
            (get_request_for_write if write else get_request)(db, user, row.id)
    elif name == "procurement.rfqs":
        from app.modules.rfqs.service import get_rfq
        for row in rows:
            try:
                get_rfq(db, user, row.id, for_write=write)
            except BusinessValidationError:
                raise ResourceNotFoundError(f"询价单 {row.id} 不存在") from None
    elif name == "procurement.orders":
        from app.modules.purchase_orders.service import get_order, read_order
        for row in rows:
            (get_order if write else read_order)(db, user, row.id)
    elif name == "warehouse.deliveries":
        from app.modules.deliveries.service import get_delivery
        for row in rows:
            get_delivery(db, user, row.id)
    elif name.startswith("finance."):
        from app.modules.finance import service
        getter = {
            "finance.reconciliations": service.get_reconciliation,
            "finance.invoices": service.get_invoice,
            "finance.payments": service.get_payment,
            "finance.settlements": service.get_settlement,
        }.get(name)
        if getter:
            for row in rows:
                getter(db, user, row.id)
    elif name == "warehouse.inventory.issues":
        from app.modules.inventory.service import get_issue_request
        for row in rows:
            get_issue_request(db, user, row.id)
    elif name == "warehouse.inventory.transfers":
        from app.modules.inventory.service import get_transfer_request
        for row in rows:
            get_transfer_request(db, user, row.id)
    elif name == "warehouse.inventory.stocktakes":
        from app.modules.inventory.service import get_stocktake_request
        for row in rows:
            get_stocktake_request(db, user, row.id)
    elif name in {"warehouse.inventory.balances", "warehouse.inventory.transactions"}:
        from app.modules.inventory.service import accessible_warehouse_ids
        allowed_warehouses = accessible_warehouse_ids(db, user)
        if allowed_warehouses is not None and any(row.warehouse_id not in allowed_warehouses for row in rows):
            raise ResourceNotFoundError("所选记录不存在")
    elif name == "quality.acceptances":
        from app.modules.quality_acceptances.service import get_acceptance
        for row in rows:
            get_acceptance(db, user, row.id)
    elif name == "operations.exceptions":
        from app.modules.operation_exceptions.service import get_exception
        for row in rows:
            get_exception(db, user, row.id)


@router.post("/{name}/delete", summary="批量停用主数据或删除草稿")
def batch_delete(name: str, selection: Selection, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int | str]:
    spec = _resource(name)
    _authorize(db, user, spec.delete_permission or spec.write_permission)
    if spec.delete_mode == "readonly":
        raise BusinessValidationError("已生效记录和流水不可删除")
    if len(set(selection.ids)) != len(selection.ids):
        raise BusinessValidationError("所选记录包含重复 ID")

    rows = _rows(db, spec, selection.ids, for_update=True)
    _authorize_row_scope(db, user, name, rows, write=True)
    if spec.delete_mode == "draft" and any(row.status != "DRAFT" for row in rows):
        raise BusinessValidationError("只能批量删除草稿；请取消选择已提交或已生效记录")
    if spec.delete_mode == "master" and name == "system.roles" and any(
        row.role_code == "SYS_ADMIN" for row in rows
    ):
        raise BusinessValidationError("系统管理员角色不能停用")
    if spec.delete_mode == "master" and name == "system.users" and user.id in selection.ids:
        raise BusinessValidationError("不能停用当前登录账号")
    if spec.delete_mode == "master" and name == "system.users":
        if any(row.status in {"PENDING", "REJECTED"} for row in rows):
            raise BusinessValidationError("注册申请只能通过专用审批操作处理")
        admin_user_ids = {
            row.id
            for row in rows
            if "SYS_ADMIN" in system_crud.get_user_role_codes(db, row.id)
        }
        if admin_user_ids:
            from app.modules.system.service import ensure_active_system_admin_remains

            ensure_active_system_admin_remains(db, admin_user_ids)
    if spec.delete_mode == "permission":
        used = db.scalar(select(RolePermission.permission_id).where(RolePermission.permission_id.in_(selection.ids)).limit(1))
        if used is not None:
            raise BusinessValidationError("所选权限仍被角色引用，不能删除")

    if name in {"system.roles", "system.permissions"}:
        from app.modules.system.service import require_authorization_admin
        require_authorization_admin(db, user.id)
    if name == "system.users":
        from app.modules.system.service import _require_role_assignment
        for row in rows:
            _require_role_assignment(db, user.id, [], target_id=row.id)

    try:
        for row in rows:
            if name.startswith("system."):
                from app.modules.system import service as system_service
                if name == "system.users":
                    system_service.delete_user(db, row.id, actor_id=user.id, commit=False)
                elif name == "system.departments":
                    system_service.delete_department(db, row.id, commit=False)
                elif name == "system.roles":
                    system_service.delete_role(db, row.id, actor_id=user.id, commit=False)
                elif name == "system.permissions":
                    system_service.delete_permission(db, row.id, actor_id=user.id, commit=False)
            elif spec.delete_mode == "master":
                from app.modules.chemicals import crud as chemical_crud
                from app.modules.products import crud as product_crud
                from app.modules.suppliers import crud as supplier_crud
                disable = {"master.chemicals": chemical_crud.disable,
                           "master.products": product_crud.disable,
                           "master.suppliers": supplier_crud.disable}[name]
                disable(db, row, commit=False)
            else:
                if name == "finance.reconciliations":
                    from app.modules.finance.model import FinanceReconciliationItem
                    from sqlalchemy import delete as sql_delete
                    db.execute(sql_delete(FinanceReconciliationItem).where(FinanceReconciliationItem.reconciliation_id == row.id))
                elif name == "finance.invoices":
                    from app.modules.files.model import SysFileAttachment
                    from app.modules.finance.model import FinanceInvoiceMatch
                    from sqlalchemy import delete as sql_delete
                    db.execute(sql_delete(FinanceInvoiceMatch).where(FinanceInvoiceMatch.invoice_id == row.id))
                    db.execute(sql_delete(SysFileAttachment).where(
                        SysFileAttachment.resource_type == "FINANCE_INVOICE",
                        SysFileAttachment.resource_id == row.id,
                    ))
                db.delete(row)
            add_audit_log(db, actor_id=user.id,
                          action_type="DISABLE" if spec.delete_mode == "master" else "DELETE",
                          resource_type=name, resource_id=row.id,
                          request_summary=f"批量{'停用' if spec.delete_mode == 'master' else '删除'} {name}",
                          result_status="SUCCESS")
        db.commit()
        if name == "master.products":
            from app.core.cache import invalidate
            invalidate("product_catalog")
        elif name == "master.suppliers":
            from app.core.cache import invalidate
            invalidate("supplier_directory")
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


EXPORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "master.chemicals": ("id", "chemical_name", "english_name", "alias_text", "cas_no", "chemical_formula", "molecular_weight", "hazard_class", "source_text", "status", "created_at", "updated_at"),
    "master.products": ("id", "product_code", "product_name", "chemical_id", "category_id", "model", "purity_value", "purity_unit", "packaging_spec", "unit_id", "safety_stock_quantity", "parameter_json", "version_no", "status", "created_at", "updated_at"),
    "master.suppliers": ("id", "supplier_code", "supplier_name", "unified_credit_code", "country_code", "region", "address", "business_scope", "cooperation_level", "payment_terms", "default_lead_days", "status", "note", "created_at", "updated_at"),
    "system.users": ("id", "username", "display_name", "department_id", "email", "phone", "status", "last_login_at", "created_at", "updated_at"),
    "system.departments": ("id", "parent_id", "department_code", "department_name", "manager_id", "status", "created_at", "updated_at"),
    "system.roles": ("id", "role_code", "role_name", "description", "status", "created_at", "updated_at"),
    "system.permissions": ("id", "permission_code", "permission_name", "permission_type", "resource", "action", "description", "created_at", "updated_at"),
    "procurement.requests": ("id", "request_no", "applicant_id", "department_id", "purpose", "priority", "budget_amount", "currency_code", "expected_date", "status", "submitted_at", "approved_at", "rejected_at", "cancelled_at", "cancel_reason", "created_at", "updated_at"),
    "procurement.rfqs": ("id", "rfq_no", "source_request_id", "requester_id", "quote_deadline", "requested_delivery_date", "delivery_requirements", "status", "sent_at", "closed_at", "created_at", "updated_at"),
    "procurement.orders": ("id", "po_no", "supplier_id", "source_comparison_id", "source_quote_id", "source_request_id", "department_id", "buyer_id", "order_amount", "currency_code", "delivery_address", "order_date", "expected_arrival_date", "status", "supplier_confirmed_at", "approved_at", "cancelled_at", "cancel_reason", "note", "created_at", "updated_at"),
    "warehouse.deliveries": ("id", "delivery_no", "po_id", "supplier_id", "shipment_date", "expected_arrival_date", "actual_arrival_date", "logistics_company", "tracking_no", "status", "received_by", "received_at", "note", "created_at", "updated_at"),
    "warehouse.inventory.balances": ("id", "warehouse_id", "location_id", "product_id", "batch_id", "unit_id", "quantity", "locked_quantity", "status", "created_at", "updated_at"),
    "warehouse.inventory.transactions": ("id", "transaction_no", "transaction_type", "warehouse_id", "location_id", "product_id", "batch_id", "unit_id", "quantity", "delivery_item_id", "source_type", "source_id", "operator_id", "note", "created_at"),
    "warehouse.inventory.issues": ("id", "issue_no", "applicant_id", "department_id", "purpose", "status", "approved_by", "approved_at", "rejected_at", "reject_reason", "cancelled_at", "completed_at", "created_at", "updated_at"),
    "warehouse.inventory.transfers": ("id", "transfer_no", "applicant_id", "purpose", "status", "approved_by", "approved_at", "rejected_at", "reject_reason", "cancelled_at", "completed_at", "created_at", "updated_at"),
    "warehouse.inventory.stocktakes": ("id", "stocktake_no", "applicant_id", "warehouse_id", "location_id", "purpose", "status", "approved_by", "approved_at", "rejected_at", "reject_reason", "cancelled_at", "completed_at", "created_at", "updated_at"),
    "quality.acceptances": ("id", "acceptance_no", "delivery_id", "inspector_id", "result", "inspection_time", "test_result", "certificate_complete", "report_file_id", "conclusion", "created_at", "updated_at"),
    "finance.reconciliations": ("id", "reconciliation_no", "po_id", "supplier_id", "currency_code", "amount_precision", "total_amount", "status", "created_by", "confirmed_by", "confirmed_at", "closed_at", "cancelled_at", "cancel_reason", "note", "created_at", "updated_at"),
    "finance.invoices": ("id", "invoice_no", "reconciliation_id", "po_id", "supplier_id", "invoice_code", "invoice_number", "invoice_date", "amount_excl_tax", "tax_amount", "amount_incl_tax", "currency_code", "status", "source_file_id", "submitted_by", "verified_by", "verified_at", "reject_reason", "note", "created_at", "updated_at"),
    "finance.payments": ("id", "payment_no", "reconciliation_id", "po_id", "supplier_id", "amount", "currency_code", "payment_method", "status", "requested_by", "approved_by", "paid_by", "approved_at", "paid_at", "transaction_ref", "reject_reason", "note", "created_at", "updated_at"),
    "finance.settlements": ("id", "settlement_no", "reconciliation_id", "po_id", "supplier_id", "settlement_amount", "currency_code", "status", "created_by", "confirmed_by", "confirmed_at", "cancelled_at", "cancel_reason", "note", "created_at", "updated_at"),
    "operations.exceptions": ("id", "exception_no", "exception_type", "source_type", "source_id", "po_id", "delivery_id", "delivery_item_id", "responsible_department_id", "owner_id", "severity", "description", "status", "due_at", "closed_by", "closed_at", "closing_note", "created_at", "updated_at"),
}


@router.post("/{name}/export", summary="将选中记录导出为 CSV")
def batch_export(name: str, selection: Selection, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    spec = _resource(name)
    _authorize(db, user, spec.read_permission)
    _authorize(db, user, f"{name}.export")
    rows = _rows(db, spec, selection.ids)
    _authorize_row_scope(db, user, name, rows)
    columns = EXPORT_COLUMNS.get(name)
    if not columns:
        raise BusinessValidationError("该功能区暂不支持导出")
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
    _authorize(db, user, f"{name}.import")
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
        _, schema = IMPORT_MODELS[name]
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
                values = schema.model_validate({key: value for key, value in record.items() if value not in ("", None)})
            except ValidationError as exc:
                raise BusinessValidationError(f"第 {line_no} 行字段校验失败：{exc.errors()[0]['loc']}") from None
            validated.append(values)
        from app.modules.chemicals.service import create_chemical
        from app.modules.products.service import create_product
        from app.modules.suppliers.service import create_supplier
        create = {"master.chemicals": create_chemical, "master.products": create_product,
                  "master.suppliers": create_supplier}[name]
        with db.begin_nested():
            for values in validated:
                row = create(db, values, commit=False)
                add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type=name,
                              resource_id=row.id, request_summary=f"批量导入 {name}", result_status="SUCCESS")
        db.commit()
        if name == "master.products":
            from app.core.cache import invalidate
            invalidate("product_catalog")
        elif name == "master.suppliers":
            from app.core.cache import invalidate
            invalidate("supplier_directory")
    except UnicodeDecodeError:
        raise BusinessValidationError("CSV 请使用 UTF-8 编码") from None
    except IntegrityError:
        raise BusinessValidationError("导入数据存在重复编码或无效关联 ID，整批未保存") from None
    return {"count": len(records)}
