"""面向业务对象的只读分析接口，所有结论均附带来源或数据边界。"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ResourceNotFoundError
from app.core.auth import get_current_user
from app.modules.chemicals.model import Chemical
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.deliveries import service as delivery_service
from app.modules.doc_kb.model import AiDocument, AiDocumentSection
from app.modules.finance.model import FinanceInvoice, FinancePayment, FinanceReconciliation, FinanceSettlement
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import InventoryBalance, InventoryBalanceStatusLog, InventoryBatch, InventoryStocktakeItem, InventoryTransaction, WarehouseLocation
from app.modules.operation_exceptions import service as exception_service
from app.modules.products.model import Product
from app.modules.purchase_orders import service as order_service
from app.modules.purchase_orders.model import PurchaseOrderItem
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.rfqs import service as rfq_service
from app.modules.rfqs.model import RFQItem, SupplierQuote, SupplierQuoteItem
from app.modules.suppliers.model import Supplier
from app.modules.system import crud as system_crud
from app.modules.system.model import User

router = APIRouter(prefix="/insights", tags=["业务分析"])


class InsightEvidence(BaseModel):
    """一条来自系统记录的事实及其来源位置。"""

    label: str
    value: str
    source: str
    path: str | None = None


class BusinessInsight(BaseModel):
    """只读分析结果；不写业务状态或执行建议动作。"""

    kind: str
    title: str
    audience: str
    summary: str
    evidence: list[InsightEvidence] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


PERMISSIONS: dict[str, str | tuple[str, ...]] = {
    "batch-impact": "warehouse.inventory.read",
    "finance-difference": ("finance.reconciliations.read", "procurement.orders.read"),
    "exception-action": "operations.exceptions.read",
    "msds-change": ("master.chemicals.read", "warehouse.inventory.read"),
    "supplier-score": ("master.suppliers.read", "procurement.orders.read", "warehouse.deliveries.read", "quality.acceptances.read"),
    "supplier-change": ("procurement.rfqs.read", "procurement.orders.read"),
    "stocktake-explain": "warehouse.inventory.stocktake.read",
    "replenishment": "warehouse.inventory.read",
    "location-advice": "warehouse.inventory.read",
}


def _result(kind: str, title: str, audience: str, summary: str) -> BusinessInsight:
    """创建带固定受众和范围说明的分析结果容器。"""
    return BusinessInsight(kind=kind, title=title, audience=audience, summary=summary)


def _evidence(result: BusinessInsight, label: str, value: object, source: str, path: str | None = None) -> None:
    """把数据库中的可读事实追加到结果中。"""
    result.evidence.append(InsightEvidence(label=label, value=str(value), source=source, path=path))


def _check_permission(db: Session, user: User, code: str | tuple[str, ...]) -> None:
    """使用现有用户角色和权限码限制分析数据。"""
    if "SYS_ADMIN" in system_crud.get_user_role_codes(db, user.id):
        return
    required = (code,) if isinstance(code, str) else code
    granted = system_crud.get_user_permission_codes(db, user.id)
    if any(item not in granted for item in required):
        raise HTTPException(status_code=403, detail="没有查看该业务分析的权限")


def _balance(db: Session, user: User, balance_id: int) -> InventoryBalance:
    """读取库存余额并校验用户可见的仓库范围。"""
    return inventory_service._require_balance_for_user(db, user, balance_id)


def _batch_impact(db: Session, user: User, balance_id: int) -> BusinessInsight:
    """从选定余额追踪该批次的可见库位、来源单和历史流水。"""
    current = _balance(db, user, balance_id)
    batch = db.get(InventoryBatch, current.batch_id)
    if batch is None:
        raise ResourceNotFoundError("库存批次不存在")
    scope = inventory_service.accessible_warehouse_ids(db, user)
    result = _result("batch-impact", f"批次 {batch.batch_no} 影响范围", "仓管、质量负责人", "仅展示当前用户可见的 ChemicalOps 记录。")
    if batch.source_delivery_id:
        source = db.get(Delivery, batch.source_delivery_id)
        if source:
            _evidence(result, "来源到货单", source.delivery_no, "到货记录", "/warehouse/deliveries")
            acceptance = db.scalar(select(QualityAcceptance).where(QualityAcceptance.delivery_id == source.id).order_by(QualityAcceptance.id.desc()).limit(1))
            if acceptance:
                _evidence(result, "关联质量验收", f"验收单 #{acceptance.id} · {acceptance.result or '待验收'}", "质量验收记录", "/quality/acceptances")
    balances = db.scalars(select(InventoryBalance).where(InventoryBalance.batch_id == batch.id)).all()
    for row in balances:
        if scope is not None and row.warehouse_id not in scope:
            continue
        location = db.get(WarehouseLocation, row.location_id)
        _evidence(result, f"库位 {location.location_name if location else row.location_id}", f"余额 {row.quantity}，锁定 {row.locked_quantity}，状态 {row.status}", f"库存余额 #{row.id}", "/warehouse/inventory")
    txs = db.scalars(select(InventoryTransaction).where(InventoryTransaction.batch_id == batch.id).order_by(InventoryTransaction.created_at.desc()).limit(100)).all()
    for row in txs:
        if scope is None or row.warehouse_id in scope:
            _evidence(result, f"流水 {row.transaction_no}", f"{row.transaction_type} {row.quantity} · {row.created_at}", f"{row.source_type or '库存流水'} #{row.source_id or row.id}", "/warehouse/transactions")
    result.suggestions.append("逐一核查列出的库位和去向；冻结或召回仍需在原库存流程中确认。")
    result.limitations.append("只展示最近 100 条流水；系统外使用、客户去向和不可见仓库无法判断。")
    return result


def _finance_difference(db: Session, user: User, order_id: int) -> BusinessInsight:
    """逐单比较采购量、收货、对账、核验发票和已付款金额。"""
    order = order_service.get_order(db, user, order_id)
    result = _result("finance-difference", f"订单 {order.po_no} 财务差异", "财务对账人员、采购员", "金额按各自币种汇总，不进行跨币种折算。")
    _evidence(result, "订单金额", f"{order.order_amount:.2f} {order.currency_code}", order.po_no, f"/procurement/purchase-orders/{order.id}")
    lines = db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == order.id)).all()
    for line in lines:
        _evidence(result, f"订单行 {line.line_no} · {line.product_name_snapshot}", f"订购 {line.order_quantity}，已收 {line.received_quantity}，未收 {line.order_quantity-line.received_quantity}", f"订单明细 #{line.id}", f"/procurement/purchase-orders/{order.id}")
    reconciliations = db.scalars(select(FinanceReconciliation).where(FinanceReconciliation.po_id == order.id)).all()
    if not reconciliations:
        result.limitations.append("当前订单没有对账单，因此无法分析发票和付款差额。")
    for rec in reconciliations:
        _evidence(result, "对账单", f"{rec.total_amount:.2f} {rec.currency_code} · {rec.status}", rec.reconciliation_no, "/finance/reconciliations")
        if rec.cancelled_at is not None:
            result.limitations.append(f"对账单 {rec.reconciliation_no} 已取消，不计入发票和付款差额。")
            continue
        invoices = db.scalars(select(FinanceInvoice).where(FinanceInvoice.reconciliation_id == rec.id)).all()
        payments = db.scalars(select(FinancePayment).where(FinancePayment.reconciliation_id == rec.id)).all()
        verified = sum((x.amount_incl_tax for x in invoices if x.status == "VERIFIED" and x.currency_code == rec.currency_code), Decimal(0))
        paid = sum((x.amount for x in payments if x.status == "PAID" and x.currency_code == rec.currency_code), Decimal(0))
        _evidence(result, "已核验发票 / 未开票差额", f"{verified:.2f} / {rec.total_amount-verified:.2f} {rec.currency_code}", rec.reconciliation_no, "/finance/invoices")
        _evidence(result, "已付款 / 未付款差额", f"{paid:.2f} / {rec.total_amount-paid:.2f} {rec.currency_code}", rec.reconciliation_no, "/finance/payments")
        settlements = db.scalars(select(FinanceSettlement).where(FinanceSettlement.reconciliation_id == rec.id)).all()
        for settlement in settlements:
            _evidence(result, "结算状态", f"{settlement.settlement_amount:.2f} {settlement.currency_code} · {settlement.status}", settlement.settlement_no, "/finance/settlements")
        if any(x.currency_code != rec.currency_code for x in [*invoices, *payments]):
            result.limitations.append(f"{rec.reconciliation_no} 包含其他币种单据，这些单据未参与汇总。")
    result.suggestions.append("先在原单据核对收货与对账口径，再处理发票和付款差额。")
    return result


def _exception_action(db: Session, user: User, exception_id: int) -> BusinessInsight:
    """整理异常的负责人、时限、任务及人工可选动作。"""
    item = exception_service.get_exception(db, user, exception_id)
    result = _result("exception-action", f"异常 {item.exception_no} 处置", "异常负责人、运营主管", item.description)
    _evidence(result, "来源对象", f"{item.source_type} #{item.source_id}", item.exception_no)
    _evidence(result, "负责人 / 状态", f"{item.owner_id or '未指定'} / {item.status}", item.exception_no)
    _evidence(result, "严重度 / 截止时间", f"{item.severity} / {item.due_at or '未设置'}", item.exception_no)
    tasks, _ = exception_service.list_tasks(db, user, exception_id, status=None, page=1, page_size=100)
    for task in tasks:
        _evidence(result, f"待办 {task.id}", f"{task.title} · {task.status} · 负责人 {task.assignee_id or '未指定'}", item.exception_no)
    result.suggestions.append("核实来源影响并确定负责人后，在异常详情中创建或更新处理任务。")
    return result


def _msds_change(db: Session, user: User, chemical_id: int) -> BusinessInsight:
    """按同 CAS 最近两份已解析 MSDS 对比章节，并列出相关产品。"""
    chemical = db.get(Chemical, chemical_id)
    if chemical is None:
        raise ResourceNotFoundError("化学品不存在")
    result = _result("msds-change", f"{chemical.chemical_name} MSDS 变更", "EHS、质量负责人", "按同 CAS 的两份最新已解析 MSDS 比较章节文本。")
    docs = db.scalars(select(AiDocument).where(AiDocument.cas_no == chemical.cas_no, AiDocument.doc_type == "msds", AiDocument.parse_status == "PARSED").order_by(AiDocument.created_at.desc()).limit(2)).all()
    if len(docs) < 2:
        result.limitations.append("少于两份已解析 MSDS，暂时无法比较版本。")
        return result
    newer, older = docs
    old_sections = {x.section_key: x for x in db.scalars(select(AiDocumentSection).where(AiDocumentSection.document_id == older.id)).all()}
    for section in db.scalars(select(AiDocumentSection).where(AiDocumentSection.document_id == newer.id)).all():
        prior = old_sections.pop(section.section_key, None)
        if prior is None or prior.content != section.content:
            _evidence(result, section.title or section.section_key, "新增章节" if prior is None else "章节内容变化，需核对原文", f"文档 #{older.id} → #{newer.id}，章节 {section.section_no}")
    for section in old_sections.values():
        _evidence(result, section.title or section.section_key, "新版中未找到", f"旧文档 #{older.id}，章节 {section.section_no}")
    products = db.scalars(select(Product).where(Product.chemical_id == chemical.id)).all()
    _evidence(result, "关联产品", "、".join(x.product_name for x in products) or "无", f"化学品 #{chemical.id}", "/master/products")
    product_ids = [x.id for x in products]
    scope = inventory_service.accessible_warehouse_ids(db, user)
    balances = db.scalars(select(InventoryBalance, InventoryBatch).join(InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id).where(InventoryBalance.product_id.in_(product_ids))).all() if product_ids else []
    for balance, batch in balances:
        if scope is not None and balance.warehouse_id not in scope:
            continue
        _evidence(result, f"在库批次 {batch.batch_no}", f"余额 {balance.quantity}，有效期 {batch.expiry_date or '未记录'}，状态 {balance.status}", f"库存余额 #{balance.id}", "/warehouse/inventory")
    result.limitations.append("章节文字差异不代表危害结论变化；当前未记录批准版次与页码，必须由 EHS 对照原始 MSDS 判断。")
    return result


def _supplier_score(db: Session, user: User, supplier_id: int) -> BusinessInsight:
    """统计供应商订单、到货及时性和短交记录，不在小样本下打总分。"""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise ResourceNotFoundError("供应商不存在")
    result = _result("supplier-score", f"{supplier.supplier_name} 履约画像", "采购员、采购主管", "按已录入的订单和到货记录展示分项指标。")
    order_page, order_count = order_service.list_orders(db, user, keyword=None, status=None, page=1, page_size=100)
    orders = [x for x in order_page if x.supplier_id == supplier_id and x.status not in {"DRAFT", "CANCELLED"}]
    delivery_page, delivery_count = delivery_service.list_deliveries(db, user, keyword=None, status=None, page=1, page_size=100)
    deliveries = [x for x in delivery_page if x.supplier_id == supplier_id]
    dated = [x for x in deliveries if x.expected_arrival_date and x.actual_arrival_date]
    timely = sum(x.actual_arrival_date <= x.expected_arrival_date for x in dated)
    _evidence(result, "采购订单", len(orders), "采购订单", "/procurement/purchase-orders")
    _evidence(result, "有完整日期的到货单", len(dated), "到货记录", "/warehouse/deliveries")
    _evidence(result, "准时到货", f"{timely}/{len(dated)}" if dated else "暂无完整日期样本", "到货记录", "/warehouse/deliveries")
    delivery_ids = [x.id for x in deliveries]
    lines = db.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id.in_(delivery_ids))).all() if delivery_ids else []
    _evidence(result, "短交明细", f"{sum(x.short_quantity > 0 for x in lines)} / {len(lines)}", "到货明细", "/warehouse/deliveries")
    acceptance_rows = db.scalars(select(QualityAcceptance).where(QualityAcceptance.delivery_id.in_(delivery_ids))).all() if delivery_ids else []
    _evidence(result, "验收结果样本", f"合格 {sum(x.result == 'PASSED' for x in acceptance_rows)}，部分合格 {sum(x.result == 'PARTIAL' for x in acceptance_rows)}，不合格 {sum(x.result == 'FAILED' for x in acceptance_rows)}", "质量验收记录", "/quality/acceptances")
    result.limitations.append("未配置评分权重、同物料可比价格和最小样本量，因此不计算综合分或推荐排名。")
    if order_count > 100 or delivery_count > 100:
        result.limitations.append("当前统计基于用户可见的最近 100 条订单及到货记录，样本不完整。")
    return result


def _supplier_change(db: Session, user: User, rfq_id: int) -> BusinessInsight:
    """将已录入报价与询价需求逐项对照，呈现价格、数量及交期。"""
    rfq = rfq_service.get_rfq(db, user, rfq_id)
    result = _result("supplier-change", f"询价 {rfq.rfq_no} 变更核对", "采购员", "比较系统中已录入的结构化报价，不自动接受供应商变更。")
    requests = {x.id: x for x in db.scalars(select(RFQItem).where(RFQItem.rfq_id == rfq.id)).all()}
    quotes = db.scalars(select(SupplierQuote).where(SupplierQuote.rfq_id == rfq.id, SupplierQuote.status == "SUBMITTED").order_by(SupplierQuote.supplier_id, SupplierQuote.quote_version)).all()
    previous: dict[tuple[int, int], SupplierQuoteItem] = {}
    for quote in quotes:
        supplier = db.get(Supplier, quote.supplier_id)
        lines = db.scalars(select(SupplierQuoteItem).where(SupplierQuoteItem.quote_id == quote.id)).all()
        for line in lines:
            request = requests.get(line.rfq_item_id)
            if request is None:
                continue
            old = previous.get((quote.supplier_id, line.rfq_item_id))
            change = "首次报价"
            if old is not None:
                change = f"单价变化 {line.unit_price-old.unit_price:+}，报价数量变化 {line.quoted_quantity-old.quoted_quantity:+}，交期 {old.lead_days or '未填'}→{line.lead_days or '未填'} 天"
            _evidence(result, f"{supplier.supplier_name if supplier else quote.supplier_id} · {request.requested_name}", f"当前报价 {line.unit_price} {quote.currency_code}，数量 {line.quoted_quantity}/{request.quantity}，交期 {line.lead_days or '未填'} 天；{change}", f"报价 {quote.quote_no}，需求行 #{request.id}", "/procurement/rfqs")
            previous[(quote.supplier_id, line.rfq_item_id)] = line
            linked_lines = db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.source_quote_item_id == line.id)).all()
            for order_line in linked_lines:
                try:
                    order = order_service.get_order(db, user, order_line.po_id)
                except ResourceNotFoundError:
                    continue
                _evidence(result, "已引用该报价的采购订单", f"{order.po_no} · 下单价 {order_line.unit_price} · 数量 {order_line.order_quantity}", f"订单明细 #{order_line.id}", f"/procurement/purchase-orders/{order.id}")
    if not quotes:
        result.limitations.append("未录入结构化报价，无法比较附件中的供应商确认函。")
    result.limitations.append("未覆盖订单行、在途库存和成本变动模拟；请回到询价记录人工核实。")
    return result


def _stocktake_explain(db: Session, user: User, stocktake_id: int) -> BusinessInsight:
    """展示盘点账实数量及相同批次、库位的近期流水。"""
    stocktake = inventory_service.get_stocktake_request(db, user, stocktake_id)
    result = _result("stocktake-explain", f"盘点 {stocktake.stocktake_no} 差异", "仓管、仓储主管", f"盘点状态：{stocktake.status}。数量保留各行原单位。")
    rows = db.scalars(select(InventoryStocktakeItem).where(InventoryStocktakeItem.stocktake_request_id == stocktake.id)).all()
    for row in rows:
        _evidence(result, f"盘点行 {row.line_no}", f"账面 {row.book_quantity}，实盘 {row.counted_quantity}，差异 {row.difference_quantity}，单位 #{row.unit_id}", f"盘点明细 #{row.id}", "/warehouse/stocktakes")
        scope = inventory_service.accessible_warehouse_ids(db, user)
        if scope is None or stocktake.warehouse_id in scope:
            txs = db.scalars(select(InventoryTransaction).where(InventoryTransaction.warehouse_id == stocktake.warehouse_id, InventoryTransaction.batch_id == row.batch_id, InventoryTransaction.location_id == row.location_id).order_by(InventoryTransaction.created_at.desc()).limit(5)).all()
            for tx in txs:
                _evidence(result, f"关联流水 {tx.transaction_no}", f"{tx.transaction_type} {tx.quantity} · {tx.created_at}", f"库存流水 #{tx.id}", "/warehouse/transactions")
            balance = db.scalar(select(InventoryBalance).where(InventoryBalance.warehouse_id == stocktake.warehouse_id, InventoryBalance.location_id == row.location_id, InventoryBalance.batch_id == row.batch_id, InventoryBalance.unit_id == row.unit_id))
            if balance:
                for change in db.scalars(select(InventoryBalanceStatusLog).where(InventoryBalanceStatusLog.balance_id == balance.id).order_by(InventoryBalanceStatusLog.created_at.desc()).limit(5)).all():
                    _evidence(result, "冻结状态变化", f"{change.previous_status} → {change.new_status} · {change.reason} · {change.created_at}", f"库存状态记录 #{change.id}", "/warehouse/inventory")
    result.limitations.append("流水按批次和库位列出最近五条，只供定位核查，不能单独证明差异原因。")
    return result


def _replenishment(db: Session, user: User, balance_id: int) -> BusinessInsight:
    """汇总三十天同产品同单位的出库记录及当前余额。"""
    balance = _balance(db, user, balance_id)
    cutoff = date.today() - timedelta(days=30)
    query = select(InventoryTransaction).where(InventoryTransaction.product_id == balance.product_id, InventoryTransaction.unit_id == balance.unit_id, InventoryTransaction.created_at >= cutoff)
    scope = inventory_service.accessible_warehouse_ids(db, user)
    txs = db.scalars(query).all()
    outbound = [x for x in txs if x.transaction_type == "OUTBOUND" and (scope is None or x.warehouse_id in scope)]
    consumed = sum((abs(x.quantity) for x in outbound), Decimal(0))
    result = _result("replenishment", "近 30 天消耗观察", "仓管、采购员", "仅按同产品、同单位的库存流水汇总，不生成采购建议量。")
    _evidence(result, "当前余额", f"{balance.quantity} · 单位 #{balance.unit_id}", f"库存余额 #{balance.id}", "/warehouse/inventory")
    _evidence(result, "已记录出库", f"{consumed} · {len(outbound)} 笔", "近 30 天库存流水", "/warehouse/transactions")
    if consumed > 0:
        daily = consumed / Decimal(30)
        cover = max(Decimal(0), balance.quantity - balance.locked_quantity) / daily
        _evidence(result, "粗略日均 / 可用量覆盖天数", f"{daily.quantize(Decimal('0.01'))} / {cover.quantize(Decimal('0.1'))} 天", "按近 30 天记录均摊估算")
    result.limitations.append("未验证历史连续性、在途量、交期稳定性及预测误差，不输出预计缺口或补货量。")
    return result


def _location_advice(db: Session, user: User, balance_id: int) -> BusinessInsight:
    """按有效期排列可见的同产品库存批次供仓管核查。"""
    balance = _balance(db, user, balance_id)
    scope = inventory_service.accessible_warehouse_ids(db, user)
    rows = db.scalars(select(InventoryBalance, InventoryBatch).join(InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id).where(InventoryBalance.product_id == balance.product_id, InventoryBalance.unit_id == balance.unit_id, InventoryBalance.quantity > 0)).all()
    rows = [(slot, batch) for slot, batch in rows if slot.status == "AVAILABLE" and (scope is None or slot.warehouse_id in scope)]
    rows.sort(key=lambda pair: pair[1].expiry_date or date.max)
    result = _result("location-advice", "库位与批次提示", "仓管", "同产品同单位的可用库存按有效期排序，供人工核查。")
    for slot, batch in rows[:10]:
        location = db.get(WarehouseLocation, slot.location_id)
        _evidence(result, batch.batch_no, f"有效期 {batch.expiry_date or '未记录'}，可用 {slot.quantity-slot.locked_quantity}，库位 {location.location_name if location else slot.location_id}", f"库存余额 #{slot.id}", "/warehouse/inventory")
    result.suggestions.append("核实储存限制、兼容性和实际作业后，再决定是否优先使用或调拨。")
    result.limitations.append("未维护库位容量、距离及化学品兼容性，暂不推荐实际库位变更。")
    return result


@router.get("/{kind}/{object_id}", response_model=BusinessInsight, summary="查询业务对象的只读分析")
def get_business_insight(kind: str, object_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> BusinessInsight:
    """检查场景权限后调用对应分析；未知场景不回退到宽泛查询。"""
    permission = PERMISSIONS.get(kind)
    if permission is None:
        raise ResourceNotFoundError("分析场景不存在")
    if object_id <= 0:
        raise ResourceNotFoundError("业务对象编号无效")
    _check_permission(db, user, permission)
    handlers = {
        "batch-impact": lambda: _batch_impact(db, user, object_id),
        "finance-difference": lambda: _finance_difference(db, user, object_id),
        "exception-action": lambda: _exception_action(db, user, object_id),
        "msds-change": lambda: _msds_change(db, user, object_id),
        "supplier-score": lambda: _supplier_score(db, user, object_id),
        "supplier-change": lambda: _supplier_change(db, user, object_id),
        "stocktake-explain": lambda: _stocktake_explain(db, user, object_id),
        "replenishment": lambda: _replenishment(db, user, object_id),
        "location-advice": lambda: _location_advice(db, user, object_id),
    }
    return handlers[kind]()
