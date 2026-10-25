"""供应商 360 的只读跨模块汇总。

只读取当前用户可见的订单、到货、验收、异常和财务记录；每个业务段
独立鉴权，缺权限时只返回该段不可见，不影响其他段。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ai.formatting import format_amount
from app.modules.ai.schema import Source, SupplierProfileInput, SupplierProfileResult
from app.modules.deliveries.model import Delivery
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation
from app.modules.operation_exceptions import service as exception_service
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.quality_acceptances.scope import acceptance_read_condition
from app.modules.suppliers.model import Supplier
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


def _section(stage: str, status: str, summary: str, *, metrics: dict[str, Any] | None = None,
             records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"stage": stage, "status": status, "summary": summary,
            "metrics": metrics or {}, "records": records or []}


def _money_by_currency(rows: list[tuple[str | None, Decimal | int]]) -> str:
    values = {currency or "未登记币种": Decimal(str(amount or 0)) for currency, amount in rows}
    return "、".join(f"{format_amount(amount)} {currency}" for currency, amount in sorted(values.items())) or "无金额"


def _build_orders(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (PurchaseOrder.supplier_id == supplier_id, order_read_condition(user, roles))
    total = db.scalar(select(func.count(PurchaseOrder.id)).where(*condition)) or 0
    status_rows = db.execute(
        select(PurchaseOrder.status, func.count(PurchaseOrder.id)).where(*condition).group_by(PurchaseOrder.status)
    ).all()
    currency_rows = db.execute(
        select(PurchaseOrder.currency_code, func.coalesce(func.sum(PurchaseOrder.order_amount), 0))
        .where(*condition).group_by(PurchaseOrder.currency_code)
    ).all()
    recent = list(db.scalars(
        select(PurchaseOrder).where(*condition).order_by(PurchaseOrder.id.desc()).limit(5)
    ).all())
    status_text = "、".join(f"{status} {count}" for status, count in status_rows) or "无"
    records = [{
        "po_no": order.po_no, "status": order.status, "order_date": order.order_date.isoformat() if order.order_date else None,
        "amount": format_amount(order.order_amount), "currency": order.currency_code,
    } for order in recent]
    summary = f"订单 {total} 笔；状态：{status_text}；金额：{_money_by_currency(currency_rows)}。"
    return _section("订单", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "by_status": {status: int(count) for status, count in status_rows}},
                    records=records)


def _build_deliveries(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (PurchaseOrder.supplier_id == supplier_id, order_read_condition(user, roles))
    total = db.scalar(select(func.count(Delivery.id)).select_from(Delivery)
                      .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(*condition)) or 0
    status_rows = db.execute(
        select(Delivery.status, func.count(Delivery.id)).select_from(Delivery)
        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(*condition).group_by(Delivery.status)
    ).all()
    received = db.scalar(select(func.count(Delivery.id)).select_from(Delivery)
                         .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
                         .where(*condition, Delivery.actual_arrival_date.is_not(None))) or 0
    on_time = db.scalar(select(func.count(Delivery.id)).select_from(Delivery)
                        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
                        .where(*condition, Delivery.actual_arrival_date.is_not(None),
                               Delivery.expected_arrival_date.is_not(None),
                               Delivery.actual_arrival_date <= Delivery.expected_arrival_date)) or 0
    overdue = db.scalar(select(func.count(Delivery.id)).select_from(Delivery)
                        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
                        .where(*condition, Delivery.expected_arrival_date < date.today(),
                               Delivery.actual_arrival_date.is_(None))) or 0
    status_text = "、".join(f"{status} {count}" for status, count in status_rows) or "无"
    rate = f"{on_time / received * 100:.1f}%" if received else "无已收货样本"
    summary = (f"到货 {total} 单；状态：{status_text}；已收 {received} 单，准时 {on_time} 单（{rate}）；"
               f"逾期未到 {overdue} 单。")
    return _section("到货", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "received": received, "on_time": on_time,
                             "overdue_open": overdue,
                             "by_status": {status: int(count) for status, count in status_rows}})


def _build_quality(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (PurchaseOrder.supplier_id == supplier_id, acceptance_read_condition(user, roles))
    rows = db.execute(
        select(QualityAcceptance.result, func.count(QualityAcceptance.id))
        .join(Delivery, Delivery.id == QualityAcceptance.delivery_id)
        .join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id)
        .where(*condition).group_by(QualityAcceptance.result)
    ).all()
    counts = {str(result): int(count) for result, count in rows}
    total = sum(counts.values())
    decided = counts.get("PASSED", 0) + counts.get("FAILED", 0)
    rate = f"{counts.get('PASSED', 0) / decided * 100:.1f}%" if decided else "无已判定样本"
    status_text = "、".join(f"{key} {value}" for key, value in sorted(counts.items())) or "无"
    summary = f"质量验收 {total} 单；结果：{status_text}；通过率 {rate}（按已判定）。"
    return _section("质量验收", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "by_result": counts, "pass_rate": rate})


def _build_exceptions(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    counts = exception_service.supplier_exception_counts(db, user, supplier_id)
    open_count = sum(count for status, count in counts.items() if status in {"OPEN", "PROCESSING", "RESOLVED"})
    status_text = "、".join(f"{key} {value}" for key, value in sorted(counts.items())) or "无"
    summary = f"关联异常 {sum(counts.values())} 条；状态：{status_text}；未关闭 {open_count} 条。"
    return _section("运营异常", "AVAILABLE" if counts else "NO_DATA", summary,
                    metrics={"total": sum(counts.values()), "open": open_count, "by_status": counts})


def _finance_scope(user: User, roles: set[str], model):
    visible_orders = select(PurchaseOrder.id).where(order_read_condition(user, roles))
    return model.po_id.in_(visible_orders)


def _build_reconciliations(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (FinanceReconciliation.supplier_id == supplier_id, _finance_scope(user, roles, FinanceReconciliation))
    total = db.scalar(select(func.count(FinanceReconciliation.id)).where(*condition)) or 0
    rows = db.execute(select(FinanceReconciliation.status, func.count(FinanceReconciliation.id))
                      .where(*condition).group_by(FinanceReconciliation.status)).all()
    amounts = db.execute(select(FinanceReconciliation.currency_code,
                                func.coalesce(func.sum(FinanceReconciliation.total_amount), 0))
                         .where(*condition).group_by(FinanceReconciliation.currency_code)).all()
    confirmed = sum(int(count) for status, count in rows if status in {"CONFIRMED", "CLOSED"})
    status_text = "、".join(f"{status} {count}" for status, count in rows) or "无"
    summary = f"对账 {total} 单（已确认/关闭 {confirmed}）；状态：{status_text}；金额：{_money_by_currency(amounts)}。"
    return _section("财务对账", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "confirmed": confirmed,
                             "by_status": {status: int(count) for status, count in rows}})


def _build_invoices(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (FinanceInvoice.supplier_id == supplier_id, _finance_scope(user, roles, FinanceInvoice))
    total = db.scalar(select(func.count(FinanceInvoice.id)).where(*condition)) or 0
    rows = db.execute(select(FinanceInvoice.status, func.count(FinanceInvoice.id))
                      .where(*condition).group_by(FinanceInvoice.status)).all()
    amounts = db.execute(select(FinanceInvoice.currency_code,
                                func.coalesce(func.sum(FinanceInvoice.amount_incl_tax), 0))
                         .where(*condition).group_by(FinanceInvoice.currency_code)).all()
    status_text = "、".join(f"{status} {count}" for status, count in rows) or "无"
    summary = f"发票 {total} 张；状态：{status_text}；含税金额：{_money_by_currency(amounts)}。"
    return _section("发票", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "by_status": {status: int(count) for status, count in rows}})


def _build_payments(db: Session, user: User, supplier_id: int, roles: set[str]) -> dict[str, Any]:
    condition = (FinancePayment.supplier_id == supplier_id, _finance_scope(user, roles, FinancePayment))
    total = db.scalar(select(func.count(FinancePayment.id)).where(*condition)) or 0
    rows = db.execute(select(FinancePayment.status, func.count(FinancePayment.id))
                      .where(*condition).group_by(FinancePayment.status)).all()
    amounts = db.execute(select(FinancePayment.currency_code, func.coalesce(func.sum(FinancePayment.amount), 0))
                         .where(*condition).group_by(FinancePayment.currency_code)).all()
    paid = sum(int(count) for status, count in rows if status == "PAID")
    status_text = "、".join(f"{status} {count}" for status, count in rows) or "无"
    summary = f"付款 {total} 笔（已付 {paid}）；状态：{status_text}；金额：{_money_by_currency(amounts)}。"
    return _section("付款", "AVAILABLE" if total else "NO_DATA", summary,
                    metrics={"total": total, "paid": paid,
                             "by_status": {status: int(count) for status, count in rows}})


def supplier_profile_tool(db: Session, user: User, arguments: SupplierProfileInput) -> SupplierProfileResult:
    """工具入口：把已校验的输入 Schema 交给只读汇总。"""

    return build_supplier_profile(db, user, arguments.supplier_code)


def build_supplier_profile(db: Session, user: User, supplier_code: str) -> SupplierProfileResult:
    """按准确供应商编码构建跨模块只读视图；无权限的段不读取数据。"""

    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    admin = "SYS_ADMIN" in roles
    supplier = db.scalar(select(Supplier).where(Supplier.supplier_code == supplier_code.strip()))
    if supplier is None:
        return SupplierProfileResult(supplier_code=supplier_code, supplier_name=None, status=None,
                                     sections=[], sources=[], answer=f"当前可访问范围内没有找到供应商编码 {supplier_code}。")

    sections: list[dict[str, Any]] = []
    builders = (
        ("procurement.orders.read", "订单", lambda: _build_orders(db, user, supplier.id, roles)),
        ("warehouse.deliveries.read", "到货", lambda: _build_deliveries(db, user, supplier.id, roles)),
        ("quality.acceptances.read", "质量验收", lambda: _build_quality(db, user, supplier.id, roles)),
        ("operations.exceptions.read", "运营异常", lambda: _build_exceptions(db, user, supplier.id, roles)),
        ("finance.reconciliations.read", "财务对账", lambda: _build_reconciliations(db, user, supplier.id, roles)),
        ("finance.invoices.read", "发票", lambda: _build_invoices(db, user, supplier.id, roles)),
        ("finance.payments.read", "付款", lambda: _build_payments(db, user, supplier.id, roles)),
    )
    for permission, stage, builder in builders:
        if admin or permission in permissions:
            sections.append(builder())
        else:
            sections.append(_section(stage, "NO_PERMISSION", "当前账号没有该环节的读取权限。"))

    visible = [section for section in sections if section["status"] != "NO_PERMISSION"]
    hidden = [section["stage"] for section in sections if section["status"] == "NO_PERMISSION"]
    header = (f"供应商 {supplier.supplier_code}（{supplier.supplier_name}）：状态 {supplier.status}；"
              f"合作级别 {supplier.cooperation_level or '未登记'}；地区 {supplier.region or '未登记'}；"
              f"默认交期 {supplier.default_lead_days if supplier.default_lead_days is not None else '未登记'} 天。")
    lines = [header]
    lines.extend(f"{section['stage']}：{section['summary']}" for section in visible)
    if hidden:
        lines.append("当前账号不可见：" + "、".join(hidden) + "。")
    if not visible:
        lines.append("当前账号只能读取供应商主数据，无法查看订单、到货、质量、异常或财务汇总。")
    lines.append("以上汇总只反映当前权限范围内的记录，不代表供应商全量表现。")
    return SupplierProfileResult(
        supplier_code=supplier.supplier_code,
        supplier_name=supplier.supplier_name,
        status=supplier.status,
        sections=sections,
        sources=[Source(resource="suppliers", record_id=supplier.id)],
        answer="\n".join(lines),
    )
