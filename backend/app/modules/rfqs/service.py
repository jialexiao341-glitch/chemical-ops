"""询价、供应商报价、比价和定标的业务逻辑。"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, DuplicateResourceError, ResourceNotFoundError
from app.modules.purchase_requests.service import get_request as get_scoped_purchase_request
from app.modules.rfqs import crud
from app.modules.rfqs.scope import rfq_read_condition, rfq_write_condition
from app.modules.rfqs.model import QuoteComparison, QuoteComparisonItem, RFQ, RFQItem, RFQSupplier, SupplierQuote, SupplierQuoteItem
from app.modules.rfqs.schema import (
    QuoteSelection,
    RFQCreate,
    RFQItemCreate,
    RFQUpdate,
    SupplierQuoteCreate,
)
from app.modules.rfqs.total_cost import calculate_total_cost
from app.modules.rfqs.recommendation import build_quote_recommendation
from app.modules.deliveries.model import Delivery
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.quality_acceptances.scope import acceptance_read_condition
from app.modules.system.audit import add_audit_log
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.file_model import SysFile
from app.modules.system.model import User


def _now() -> datetime:
    """返回当前本地时间。"""

    return datetime.now()


def _ensure_unique(values: list[int], label: str) -> None:
    """检查列表中是否存在重复主键。"""

    if len(values) != len(set(values)):
        raise BusinessValidationError(f"{label}不能重复")


def _validate_item_refs(db: Session, items: list[RFQItemCreate], source_request_id: int | None) -> None:
    """校验询价明细关联的采购申请、产品和计量单位。"""

    source_items = {}
    if source_request_id is not None:
        request = crud.get_request(db, source_request_id)
        if request is None:
            raise ResourceNotFoundError("来源采购申请不存在")
        if request.status != "APPROVED":
            raise BusinessValidationError("只有已审批的采购申请才能发起询价")
        source_items = {item.id: item for item in request.items}

    for item in items:
        if item.source_request_item_id is not None:
            source_item = source_items.get(item.source_request_item_id)
            if source_item is None:
                raise BusinessValidationError("询价明细引用的采购申请明细不属于来源申请")
        if item.product_id is not None:
            product = crud.get_product(db, item.product_id)
            if product is None:
                raise ResourceNotFoundError(f"产品 {item.product_id} 不存在")
            if product.status != "ACTIVE":
                raise BusinessValidationError(f"产品 {product.product_code} 当前不可采购")
        unit = crud.get_unit(db, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")


def _validate_suppliers(db: Session, supplier_ids: list[int]) -> None:
    """校验邀请供应商是否存在且启用。"""

    _ensure_unique(supplier_ids, "供应商")
    for supplier_id in supplier_ids:
        supplier = crud.get_supplier(db, supplier_id)
        if supplier is None:
            raise ResourceNotFoundError(f"供应商 {supplier_id} 不存在")
        if supplier.status != "ACTIVE":
            raise BusinessValidationError(f"供应商 {supplier.supplier_code} 当前不可询价")


def _replace_items(db: Session, rfq: RFQ, items: list[RFQItemCreate]) -> None:
    """替换询价单明细。"""

    rfq.items.clear()
    for line_no, item in enumerate(items, start=1):
        rfq.items.append(RFQItem(line_no=line_no, **item.model_dump()))


def _replace_suppliers(rfq: RFQ, supplier_ids: list[int]) -> None:
    """替换询价单邀请供应商。"""

    rfq.suppliers.clear()
    for supplier_id in supplier_ids:
        rfq.suppliers.append(RFQSupplier(supplier_id=supplier_id, invitation_channel="MANUAL"))


def create_rfq(db: Session, user: User, data: RFQCreate, *, commit: bool = True) -> RFQ:
    """创建询价草稿。"""

    if data.source_request_id is not None:
        get_scoped_purchase_request(db, user, data.source_request_id)
    else:
        from app.modules.purchase_requests.service import _validate_department_scope
        _validate_department_scope(db, user, user.department_id)
    _validate_item_refs(db, data.items, data.source_request_id)
    _validate_suppliers(db, data.supplier_ids)
    rfq = RFQ(
        rfq_no=f"TEMP-{user.id}-{int(_now().timestamp())}",
        source_request_id=data.source_request_id,
        requester_id=user.id,
        quote_deadline=data.quote_deadline,
        requested_delivery_date=data.requested_delivery_date,
        delivery_requirements=data.delivery_requirements,
    )
    _replace_items(db, rfq, data.items)
    _replace_suppliers(rfq, data.supplier_ids)
    db.add(rfq)
    db.flush()
    rfq.rfq_no = f"RFQ{date.today():%Y%m%d}{rfq.id:06d}"
    add_audit_log(db, actor_id=user.id, action_type="CREATE", resource_type="RFQ", resource_id=rfq.id, request_summary="创建询价草稿", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    return rfq


def list_rfqs(db: Session, user: User, *, keyword: str | None, status: str | None, page: int, page_size: int):
    """按用户数据范围分页查询询价单。"""

    scope = rfq_read_condition(user, get_user_role_codes(db, user.id))
    return crud.list_page(db, scope_condition=scope, keyword=keyword, status=status, page=page, page_size=page_size)


def get_rfq(db: Session, user: User, rfq_id: int, *, for_update: bool = False, for_write: bool = False) -> RFQ:
    """查询询价详情并执行基础数据范围校验。"""

    rfq = crud.get_by_id(db, rfq_id, for_update=for_update)
    if rfq is None:
        raise ResourceNotFoundError("询价单不存在")
    roles = get_user_role_codes(db, user.id)
    scope = rfq_write_condition(user, roles) if for_write else rfq_read_condition(user, roles)
    if db.scalar(select(RFQ.id).where(RFQ.id == rfq_id, scope)) is None:
        raise BusinessValidationError("无权查看其他用户创建的询价单")
    return rfq


def update_rfq(db: Session, user: User, rfq_id: int, data: RFQUpdate) -> RFQ:
    """更新询价草稿。"""

    rfq = get_rfq(db, user, rfq_id, for_write=True)
    if rfq.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的询价单可以修改")
    values = data.model_dump(exclude_unset=True)
    if "items" in values:
        if rfq.source_request_id is not None:
            get_scoped_purchase_request(db, user, rfq.source_request_id)
        _validate_item_refs(db, data.items or [], rfq.source_request_id)
        _replace_items(db, rfq, data.items or [])
        values.pop("items")
    if "supplier_ids" in values:
        _validate_suppliers(db, data.supplier_ids or [])
        _replace_suppliers(rfq, data.supplier_ids or [])
        values.pop("supplier_ids")
    for key, value in values.items():
        setattr(rfq, key, value)
    add_audit_log(db, actor_id=user.id, action_type="UPDATE", resource_type="RFQ", resource_id=rfq.id, request_summary="更新询价草稿", result_status="SUCCESS")
    db.commit()
    return crud.get_by_id(db, rfq.id)


def send_rfq(db: Session, user: User, rfq_id: int, *, commit: bool = True) -> RFQ:
    """发送询价并进入等待报价状态。"""

    rfq = get_rfq(db, user, rfq_id, for_update=True, for_write=True)
    if rfq.status != "DRAFT":
        raise BusinessValidationError("只有草稿状态的询价单可以发送")
    if not rfq.items or not rfq.suppliers:
        raise BusinessValidationError("询价单必须包含明细和邀请供应商")
    rfq.status = "SENT"
    rfq.sent_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="SEND", resource_type="RFQ", resource_id=rfq.id, request_summary="发送询价单", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    db.flush()
    return rfq


def create_quote(db: Session, user: User, rfq_id: int, data: SupplierQuoteCreate) -> RFQ:
    """录入一份供应商报价，并更新供应商响应状态。"""

    rfq = get_rfq(db, user, rfq_id, for_write=True)
    return create_quote_for_supplier(db, user, rfq, data.supplier_id, data)


def create_quote_for_supplier(
    db: Session,
    user: User,
    rfq: RFQ,
    supplier_id: int,
    data: SupplierQuoteCreate,
) -> RFQ:
    """为已邀请的供应商创建一版报价；调用方负责授权询价范围。"""

    # 定标与所有报价入口使用同一主单锁，刷新会话中的旧状态。
    rfq = db.scalar(select(RFQ).where(RFQ.id == rfq.id).with_for_update().execution_options(populate_existing=True))
    if rfq is None:
        raise ResourceNotFoundError("询价单不存在")
    if rfq.status not in {"SENT", "RESPONDING"}:
        raise BusinessValidationError("当前询价单不接受供应商报价")
    if data.source_file_id is not None:
        source_file = db.get(SysFile, data.source_file_id)
        if source_file is None or source_file.uploader_id != user.id or source_file.file_category != "SUPPLIER_QUOTE":
            raise BusinessValidationError("报价来源文件不存在或不属于当前报价人")
    supplier = crud.get_supplier(db, supplier_id)
    if supplier is None:
        raise ResourceNotFoundError("供应商不存在")
    if supplier.status != "ACTIVE":
        raise BusinessValidationError("供应商已停用，不能录入报价")
    invitation = crud.get_invitation(db, rfq.id, supplier_id)
    if invitation is None:
        raise BusinessValidationError("该供应商未被邀请参与本次询价")
    item_ids = {item.id for item in rfq.items}
    seen_item_ids = [item.rfq_item_id for item in data.items]
    _ensure_unique(seen_item_ids, "报价明细")
    if not set(seen_item_ids).issubset(item_ids):
        raise BusinessValidationError("报价明细必须引用当前询价单明细")
    for item in data.items:
        unit = crud.get_unit(db, item.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"报价计量单位 {item.unit_id} 不存在或已停用")
        if item.moq_unit_id is not None:
            moq_unit = crud.get_unit(db, item.moq_unit_id)
            if moq_unit is None or moq_unit.status != "ACTIVE":
                raise BusinessValidationError(f"最小起订量单位 {item.moq_unit_id} 不存在或已停用")
    existing_version = db.scalar(
        select(SupplierQuote.quote_version)
        .where(SupplierQuote.rfq_id == rfq.id, SupplierQuote.supplier_id == supplier_id)
        .order_by(SupplierQuote.quote_version.desc())
        .limit(1).with_for_update()
    )
    quote = SupplierQuote(
        quote_no=f"TEMP-Q-{rfq.id}-{supplier_id}-{int(_now().timestamp())}",
        rfq_id=rfq.id,
        supplier_id=supplier_id,
        quote_version=(existing_version or 0) + 1,
        quote_date=data.quote_date or date.today(),
        valid_until=data.valid_until,
        currency_code=data.currency_code,
        status="SUBMITTED",
        source_file_id=data.source_file_id,
        received_by=user.id,
        note=data.note,
    )
    quote.items = [SupplierQuoteItem(**item.model_dump()) for item in data.items]
    db.add(quote)
    db.flush()
    quote.quote_no = f"Q{date.today():%Y%m%d}{quote.id:06d}"
    invitation.response_status = "RESPONDED"
    invitation.response_at = _now()
    rfq.status = "RESPONDING"
    add_audit_log(db, actor_id=user.id, action_type="SUBMIT_QUOTE", resource_type="RFQ", resource_id=rfq.id, request_summary=f"录入供应商 {supplier.supplier_code} 报价", result_status="SUCCESS")
    db.commit()
    # 会话保留已加载对象；按 rfq_id 新增报价不会更新已有 quotes 集合。
    db.expire(rfq, ["quotes"])
    return crud.get_by_id(db, rfq.id)


def build_comparison(db: Session, user: User, rfq_id: int) -> QuoteComparison:
    """按统一币种、单位和税务口径生成可解释的报价比价快照。"""

    rfq = get_rfq(db, user, rfq_id, for_write=True)
    quotes = [quote for quote in rfq.quotes if quote.status == "SUBMITTED"]
    if not quotes:
        raise BusinessValidationError("当前询价单还没有可比较的报价")
    comparison = QuoteComparison(
        comparison_no=f"TEMP-C-{rfq.id}-{int(_now().timestamp())}",
        rfq_id=rfq.id,
        created_by=user.id,
        conclusion="仅在币种、计量单位、税率及含税口径一致的报价组内按单价排序；不做汇率或单位换算。总成本按询价量/同单位 MOQ、商品税与已登记运费拆分；缺项不生成完整总额。MOQ、交期、账期和当前用户可见的历史验收结果作为独立事实展示，不合成评分；最终中选仍需人工确认。",
        status="DRAFT",
    )
    db.add(comparison)
    db.flush()
    comparison.comparison_no = f"QC{date.today():%Y%m%d}{comparison.id:06d}"
    rfq_items = {item.id: item for item in rfq.items}
    candidates = defaultdict(list)
    incomplete_quote_ids = set()
    for quote in quotes:
        quoted_item_ids = {item.rfq_item_id for item in quote.items}
        if quoted_item_ids != set(rfq_items):
            incomplete_quote_ids.add(quote.id)
        for item in quote.items:
            if item.rfq_item_id in rfq_items:
                candidates[item.rfq_item_id].append((quote, item))
    for quote in quotes:
        quoted_item_ids = {item.rfq_item_id for item in quote.items}
        for rfq_item_id in set(rfq_items) - quoted_item_ids:
            candidates[rfq_item_id].append((quote, None))

    for rfq_item_id, entries in candidates.items():
        rfq_item = rfq_items[rfq_item_id]
        rows = []
        for quote, item in entries:
            reasons = []
            if quote.id in incomplete_quote_ids:
                reasons.append("报价未覆盖全部询价明细")
            if item is None:
                reasons.append("缺少该询价明细报价")
            else:
                if item.unit_id != rfq_item.unit_id:
                    reasons.append("报价计量单位与询价单位不一致")
                if item.tax_rate is None:
                    reasons.append("税率缺失")
                if item.tax_included is None:
                    reasons.append("含税口径缺失")
            row = QuoteComparisonItem(
                quote_id=quote.id,
                rfq_item_id=rfq_item_id,
                supplier_id=quote.supplier_id,
                quoted_unit_price=item.unit_price if item else None,
                total_amount=item.unit_price * item.quoted_quantity if item else None,
                currency_code=quote.currency_code,
                unit_id=item.unit_id if item else None,
                tax_rate=item.tax_rate if item else None,
                tax_included=item.tax_included if item else None,
                moq_quantity=item.moq_quantity if item else None,
                lead_days=item.lead_days if item else None,
                payment_terms=item.payment_terms if item else None,
                freight_amount=item.freight_amount if item else None,
                freight_tax_rate=item.freight_tax_rate if item else None,
                freight_tax_included=item.freight_tax_included if item else None,
                rank_no=None,
                selection_flag=0,
                comparison_status="NOT_COMPARABLE",
                comparison_reasons=reasons,
                note=item.note if item else None,
            )
            comparison.items.append(row)
            rows.append((quote, item, row, reasons))

        eligible = [entry for entry in rows if not entry[3]]
        groups = defaultdict(list)
        for entry in eligible:
            quote, item, _row, _reasons = entry
            groups[(quote.currency_code, item.tax_rate, item.tax_included)].append(entry)
        if not groups:
            continue
        largest_group_size = max(map(len, groups.values()))
        largest_groups = [group for group in groups.values() if len(group) == largest_group_size]
        if len(largest_groups) != 1:
            signatures = list(groups)
            for _quote, _item, row, reasons in eligible:
                if len({signature[0] for signature in signatures}) > 1:
                    reasons.append("币种存在差异")
                if len({signature[1] for signature in signatures}) > 1:
                    reasons.append("税率存在差异")
                if len({signature[2] for signature in signatures}) > 1:
                    reasons.append("含税口径存在差异")
                row.comparison_reasons = [*reasons, "多种报价口径数量相同，无法确定统一比较组"]
            continue
        winning_group = largest_groups[0]
        benchmark = winning_group[0]
        benchmark_quote, benchmark_item = benchmark[0], benchmark[1]
        for entry in eligible:
            quote, item, row, reasons = entry
            if entry not in winning_group:
                if quote.currency_code != benchmark_quote.currency_code:
                    reasons.append(f"币种与主要比较组不一致（{quote.currency_code} / {benchmark_quote.currency_code}）")
                if item.tax_rate != benchmark_item.tax_rate:
                    reasons.append("税率与主要比较组不一致")
                if item.tax_included != benchmark_item.tax_included:
                    reasons.append("含税口径与主要比较组不一致")
                row.comparison_reasons = reasons
                continue
            row.comparison_status = "COMPARABLE"
        ranked = sorted(winning_group, key=lambda entry: (entry[1].unit_price, entry[0].id))
        for rank, (_quote, _item, row, _reasons) in enumerate(ranked, start=1):
            row.rank_no = rank
    for row in comparison.items:
        quote = next((quote for quote in quotes if quote.id == row.quote_id), None)
        rfq_item = rfq_items.get(row.rfq_item_id)
        quote_item = next((item for item in quote.items if item.rfq_item_id == row.rfq_item_id), None) if quote else None
        if rfq_item is None or quote_item is None:
            row.analysis_json = {
                "complete": False,
                "total_cost": None,
                "reasons": ["缺少询价或报价明细"],
            }
            continue
        costs = calculate_total_cost(
            requested_quantity=rfq_item.quantity,
            requested_unit_id=rfq_item.unit_id,
            quoted_unit_id=quote_item.unit_id,
            unit_price=quote_item.unit_price,
            tax_rate=quote_item.tax_rate,
            tax_included=quote_item.tax_included,
            moq_quantity=quote_item.moq_quantity,
            moq_unit_id=quote_item.moq_unit_id,
            freight_amount=quote_item.freight_amount,
            freight_tax_rate=quote_item.freight_tax_rate,
            freight_tax_included=quote_item.freight_tax_included,
        )
        row.analysis_json = {
            "currency_code": row.currency_code,
            "purchase_quantity": str(costs.purchase_quantity) if costs.purchase_quantity is not None else None,
            "moq_extra_quantity": str(costs.moq_extra_quantity) if costs.moq_extra_quantity is not None else None,
            "goods_amount": str(costs.goods_amount) if costs.goods_amount is not None else None,
            "goods_tax": str(costs.goods_tax) if costs.goods_tax is not None else None,
            "freight_amount": str(costs.freight_amount) if costs.freight_amount is not None else None,
            "freight_tax": str(costs.freight_tax) if costs.freight_tax is not None else None,
            "total_cost": str(costs.total_cost) if costs.total_cost is not None else None,
            "complete": costs.complete,
            "reasons": costs.reasons,
            "lead_days": row.lead_days,
            "payment_terms": row.payment_terms,
        }
    add_audit_log(db, actor_id=user.id, action_type="COMPARE", resource_type="RFQ", resource_id=rfq.id, request_summary="生成供应商报价比较结果", result_status="SUCCESS")
    db.commit()
    saved_comparison = crud.get_comparison(db, rfq.id, comparison.id)
    quality_history = quality_history_by_supplier(db, user, {row.supplier_id for row in saved_comparison.items})
    for row in saved_comparison.items:
        row.quality_history = quality_history.get(row.supplier_id)
    saved_comparison.decision_analysis = _decision_analysis(saved_comparison, set(rfq_items))
    return saved_comparison


def get_latest_comparison(db: Session, user: User, rfq_id: int) -> QuoteComparison:
    """查询询价单最近一次已生成的比价结果。"""

    rfq = get_rfq(db, user, rfq_id)
    comparison = crud.get_latest_comparison(db, rfq_id)
    if comparison is None:
        raise ResourceNotFoundError("当前询价单还没有比价结果")
    quality_history = quality_history_by_supplier(db, user, {row.supplier_id for row in comparison.items})
    for row in comparison.items:
        row.quality_history = quality_history.get(row.supplier_id)
    comparison.decision_analysis = _decision_analysis(comparison, {item.id for item in rfq.items})
    return comparison


def _decision_analysis(comparison: QuoteComparison, expected_item_ids: set[int]) -> dict:
    """把当前比价快照转成非持久化的成本候选及风险摘要。"""
    return build_quote_recommendation(
        [
            {
                "quote_id": row.quote_id,
                "supplier_id": row.supplier_id,
                "rfq_item_id": row.rfq_item_id,
                "currency_code": row.currency_code,
                "comparison_status": row.comparison_status,
                "cost_analysis": row.cost_analysis,
                "lead_days": row.lead_days,
                "payment_terms": row.payment_terms,
                "quality_history": row.quality_history,
            }
            for row in comparison.items
        ],
        expected_item_ids=expected_item_ids,
    )


def quality_history_by_supplier(
    db: Session,
    user: User,
    supplier_ids: set[int],
    *,
    permission_codes: list[str] | set[str] | None = None,
    role_codes: list[str] | set[str] | None = None,
) -> dict[int, dict]:
    """只在当前用户有质量读取权限时，按质量模块现有范围汇总已完成验收事实。"""
    permissions = set(permission_codes) if permission_codes is not None else set(get_user_permission_codes(db, user.id))
    if not supplier_ids or "quality.acceptances.read" not in permissions:
        return {
            supplier_id: {"status": "UNKNOWN", "reason": "当前账号无质量验收读取权限"}
            for supplier_id in supplier_ids
        }
    roles = list(role_codes) if role_codes is not None else get_user_role_codes(db, user.id)
    rows = db.execute(
        select(PurchaseOrder.supplier_id, QualityAcceptance.result, func.count().label("count"))
        .join(Delivery, Delivery.po_id == PurchaseOrder.id)
        .join(QualityAcceptance, QualityAcceptance.delivery_id == Delivery.id)
        .where(
            PurchaseOrder.supplier_id.in_(supplier_ids),
            QualityAcceptance.result.in_(["PASSED", "PARTIAL", "FAILED"]),
            acceptance_read_condition(user, roles),
        )
        .group_by(PurchaseOrder.supplier_id, QualityAcceptance.result)
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for supplier_id, result, count in rows:
        counts.setdefault(supplier_id, {})[result] = int(count)
    summaries = {}
    for supplier_id in supplier_ids:
        outcomes = counts.get(supplier_id, {})
        sample_count = sum(outcomes.values())
        if not sample_count:
            summaries[supplier_id] = {"status": "UNKNOWN", "reason": "没有可见的已完成质量验收记录"}
        else:
            summaries[supplier_id] = {
                "status": "OBSERVED",
                "sample_count": sample_count,
                "passed": outcomes.get("PASSED", 0),
                "partial": outcomes.get("PARTIAL", 0),
                "failed": outcomes.get("FAILED", 0),
                "description": "可见的历史验收结果；仅为事实统计，不等同供应商风险评分",
            }
    return summaries


def select_quote(db: Session, user: User, rfq_id: int, data: QuoteSelection, *, commit: bool = True) -> RFQ:
    """确认中选报价，关闭询价单并拒绝其他未中选报价。"""

    # 固定锁序：询价单 -> 比价单；锁定读取刷新已有 identity map。
    db.scalar(select(RFQ).where(RFQ.id == rfq_id).with_for_update().execution_options(populate_existing=True))
    rfq = get_rfq(db, user, rfq_id, for_write=True)
    if rfq.status == "CLOSED":
        raise DuplicateResourceError("询价单已经完成定标，不能重复确认")
    comparison = db.scalar(select(QuoteComparison).where(
        QuoteComparison.id == data.comparison_id, QuoteComparison.rfq_id == rfq.id,
    ).with_for_update().execution_options(populate_existing=True))
    if comparison is None:
        raise ResourceNotFoundError("比价结果不存在")
    if comparison.status != "DRAFT":
        raise DuplicateResourceError("该比价结果已经确认或取消")
    quote = crud.get_quote(db, data.quote_id, for_update=True)
    if quote is None or quote.rfq_id != rfq.id:
        raise BusinessValidationError("中选报价不属于当前询价单")
    if quote.status != "SUBMITTED":
        raise BusinessValidationError("只有已提交的报价可以中选")
    if quote.id not in {item.quote_id for item in comparison.items}:
        raise BusinessValidationError("中选报价不在该比价结果快照中")
    comparison.selected_quote_id = quote.id
    comparison.selection_reason = data.selection_reason
    comparison.status = "CONFIRMED"
    comparison.confirmed_by = user.id
    comparison.confirmed_at = _now()
    for item in comparison.items:
        item.selection_flag = 1 if item.quote_id == quote.id else 0
    for other_quote in rfq.quotes:
        if other_quote.id == quote.id:
            other_quote.status = "SELECTED"
        elif other_quote.status == "SUBMITTED":
            other_quote.status = "REJECTED"
    rfq.status = "CLOSED"
    rfq.closed_at = _now()
    add_audit_log(db, actor_id=user.id, action_type="SELECT_QUOTE", resource_type="RFQ", resource_id=rfq.id, request_summary=f"确认中选报价 {quote.quote_no}", result_status="SUCCESS")
    if commit:
        db.commit()
        return crud.get_by_id(db, rfq.id)
    db.flush()
    return rfq
