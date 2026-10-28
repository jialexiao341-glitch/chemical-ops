"""页面对象上下文解析与只读 Copilot 回答。

页面只提交对象引用，本模块按当前用户重新读取业务对象、执行权限校验，
再基于既有订单追溯能力生成确定性回答；不接受客户端提交业务字段快照。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AuthorizationError, BusinessValidationError
from app.modules.ai.formatting import format_amount, format_decimal
from app.modules.ai.order_trace import format_stage_line, trace_purchase_order
from app.modules.ai.schema import (
    AIContextAskRequest,
    AIContextAskResponse,
    AIContextSnapshot,
)
from app.modules.finance import service as finance_service
from app.modules.deliveries import service as delivery_service
from app.modules.deliveries.model import Delivery
from app.modules.inventory import service as inventory_service
from app.modules.inventory.model import InventoryBatch, Warehouse, WarehouseLocation
from app.modules.products.model import Product
from app.modules.purchase_orders.service import get_order, read_order
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.purchase_requests.service import get_request as get_purchase_request
from app.modules.purchase_requests.model import Unit
from app.modules.quality_acceptances import service as quality_acceptance_service
from app.modules.rfqs.model import RFQ
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User
from app.modules.suppliers import service as supplier_service
from app.modules.suppliers.model import Supplier

# 问题只用来在既有追溯结果中定位环节，不参与权限判断或数据读取；
# 词表取自追溯的固定环节名及其业务同义词，避免为单句问法增加分支。
STAGE_QUESTION_MARKERS: dict[str, tuple[str, ...]] = {
    "采购申请": ("采购申请", "申请单", "请购"),
    "询价与报价": ("询价", "报价", "比价", "中选"),
    "采购订单": ("采购订单",),
    "到货": ("到货", "收货", "交期"),
    "质量验收": ("质量验收", "验收", "质检", "质量"),
    "库存": ("库存", "批次"),
    "退货": ("退货",),
    "财务对账": ("对账",),
    "发票": ("发票",),
    "付款": ("付款",),
    "结算": ("结算",),
}
FINANCE_STAGES = ("财务对账", "发票", "付款", "结算")


def _focus_stages(question: str) -> list[str]:
    """按问题命中的环节聚焦；财务问题展开为完整对账链路，便于看到未完成原因。"""

    matched = [
        stage
        for stage, markers in STAGE_QUESTION_MARKERS.items()
        if any(marker in question for marker in markers)
    ]
    if set(matched) & set(FINANCE_STAGES):
        return [stage for stage in STAGE_QUESTION_MARKERS if stage in FINANCE_STAGES]
    return matched


def _answer_for_question(question: str, trace: dict) -> str:
    """问题命中环节时给出聚焦回答；未命中时保留完整追溯，避免漏掉业务事实。"""

    names = _focus_stages(question)
    stages = [stage for stage in trace.get("stages") or [] if stage["stage"] in names]
    if not names or not stages:
        return str(trace.get("answer") or "当前可见数据不足以回答该问题。")
    lines = [
        f"订单 {trace.get('po_no')} 的{'、'.join(names)}情况",
        f"供应商：{trace.get('supplier') or '未登记'}；订单状态：{trace.get('order_status')}。",
    ]
    lines.extend(format_stage_line(stage) for stage in stages)
    conclusion = trace.get("conclusion") or []
    if set(names) & set(FINANCE_STAGES) and conclusion:
        lines.append("可见数据中的未完成原因：" + "；".join(conclusion) + "。")
    elif any(stage["status"] == "NO_PERMISSION" for stage in stages):
        lines.append("相关环节中部分数据需要更多权限才能核验。")
    else:
        lines.append("相关环节未发现未完成项。")
    lines.append("本次只展示与问题相关的环节；需要全部环节可直接问“全流程”。")
    return "\n".join(lines)


def _purchase_order_snapshot(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取当前用户可见的采购订单，并复用订单跨模块追溯作为回答证据。"""
    order = get_order(db, user, object_id)
    trace = trace_purchase_order(db, user, order.po_no)
    summary = [
        f"订单状态：{order.status}",
        f"供应商：{trace.get('supplier') or '未登记'}",
        f"订单金额：{format_amount(order.order_amount)} {order.currency_code}",
    ]
    if order.expected_arrival_date:
        summary.append(f"预计到货日期：{order.expected_arrival_date.isoformat()}")
    snapshot = AIContextSnapshot(
        object_type="purchase_order",
        object_id=order.id,
        title=f"采购订单 {order.po_no}",
        reference_no=order.po_no,
        status=order.status,
        summary=summary,
        source_records=trace.get("source_records") or [],
        suggested_questions=[
            "这单为什么还没结算？",
            "还差哪些单据或环节？",
            "卡在哪一步？",
            "相关到货、验收和发票情况如何？",
        ],
    )
    return snapshot, trace


def _purchase_request_trace(db: Session, user: User, request: object) -> tuple[list[dict], list[dict]]:
    """追踪申请关联的询价与订单；每个模块均先校验权限和数据范围。"""
    permissions = set(get_user_permission_codes(db, user.id))
    roles = set(get_user_role_codes(db, user.id))
    from app.modules.rfqs.scope import rfq_read_condition
    stages: list[dict] = []
    sources: list[dict] = []

    approval_records = [
        {"number": item.node_name, "status": item.action}
        for item in request.approvals
    ]
    sources.extend(
        {"dataset": "purchase_request_approvals", "record_id": item.id, "label": f"审批节点 {item.node_name}"}
        for item in request.approvals
    )
    approval_summary = (
        "没有查到审批节点记录" if not approval_records and request.status in {"APPROVING", "SUBMITTED"}
        else "申请尚未进入审批流程" if not approval_records
        else "找到申请审批节点"
    )
    stages.append({
        "stage": "申请审批",
        "status": "AVAILABLE" if approval_records else "NO_DATA",
        "summary": approval_summary,
        "records": approval_records,
    })

    rfq_allowed = "SYS_ADMIN" in roles or "procurement.rfqs.read" in permissions
    rfqs: list[RFQ] = []
    if rfq_allowed:
        rfq_query = (
            select(RFQ)
            .options(selectinload(RFQ.quotes), selectinload(RFQ.comparisons))
            .where(RFQ.source_request_id == request.id)
            .order_by(RFQ.id)
            .limit(51)
        )
        rfq_query = rfq_query.where(rfq_read_condition(user, roles))
        rfqs = list(db.scalars(rfq_query).all())
        rfq_records = []
        for rfq in rfqs[:50]:
            comparisons = rfq.comparisons
            rfq_records.append({
                "number": rfq.rfq_no,
                "status": rfq.status,
                "quote_count": len(rfq.quotes),
                "comparison_status": ", ".join(item.status for item in comparisons) or None,
            })
            sources.append({"dataset": "rfqs", "record_id": rfq.id, "label": f"询价单 {rfq.rfq_no}"})
        rfq_status = "AVAILABLE" if rfq_records else "NO_DATA"
        rfq_summary = "找到关联询价记录" if rfq_records else "没有查到当前账号范围内的关联记录"
        stages.append({"stage": "询价与报价", "status": rfq_status, "summary": rfq_summary, "records": rfq_records})
    else:
        stages.append({"stage": "询价与报价", "status": "NO_PERMISSION", "summary": "当前账号没有询价与报价读取权限", "records": []})

    order_allowed = "SYS_ADMIN" in roles or "procurement.orders.read" in permissions
    traces: list[dict] = []
    visible_orders: list[PurchaseOrder] = []
    if order_allowed:
        visible_orders = list(db.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.source_request_id == request.id, order_read_condition(user, roles))
            .order_by(PurchaseOrder.id)
            .limit(51)
        ).all())
        for order in visible_orders:
            traces.append(trace_purchase_order(db, user, order.po_no))
            sources.append({"dataset": "purchase_orders", "record_id": order.id, "label": f"采购订单 {order.po_no}"})
    order_records = [{"number": order.po_no, "status": order.status} for order in visible_orders]
    stages.append({
        "stage": "采购订单",
        "status": "AVAILABLE" if order_records else "NO_DATA" if order_allowed else "NO_PERMISSION",
        "summary": "找到关联采购订单" if order_records else "没有查到关联记录" if order_allowed else "当前账号没有采购订单读取权限",
        "records": order_records,
    })

    if traces:
        downstream_names = [stage["stage"] for stage in traces[0]["stages"] if stage["stage"] not in {"采购申请", "询价与报价", "采购订单"}]
        for name in downstream_names:
            related = [stage for trace in traces for stage in trace["stages"] if stage["stage"] == name]
            records = [record for stage in related for record in stage.get("records", [])]
            denied = all(stage["status"] == "NO_PERMISSION" for stage in related)
            stages.append({
                "stage": name,
                "status": "NO_PERMISSION" if denied else "AVAILABLE" if records else "NO_DATA",
                "summary": "当前账号没有该环节的读取权限" if denied else "、".join(dict.fromkeys(stage.get("summary", "") for stage in related if stage.get("summary"))) or "没有查到关联记录",
                "records": records,
            })
            for trace in traces:
                sources.extend(source for source in trace["source_records"] if source not in sources)

    return stages, sources


def _purchase_request_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, str, list[dict], object, list[dict]]:
    """读取当前用户可见的采购申请，并生成只读摘要和明细来源。"""
    request = get_purchase_request(db, user, object_id)
    summary = [f"申请状态：{request.status}", f"采购用途：{request.purpose}"]
    if request.budget_amount is not None:
        summary.append(f"预算金额：{format_amount(request.budget_amount)} {request.currency_code}")
    if request.expected_date:
        summary.append(f"期望到货日期：{request.expected_date.isoformat()}")
    if request.items:
        summary.append(f"采购明细：{len(request.items)} 行")
    sources = [{
        "dataset": "purchase_requests", "record_id": request.id,
        "label": f"采购申请 {request.request_no}",
    }, *[
        {"dataset": "purchase_request_items", "record_id": item.id,
         "label": f"采购明细 {item.line_no}：{item.requested_name}"}
        for item in request.items
    ]]
    stages, trace_sources = _purchase_request_trace(db, user, request)
    flow_answer = "\n".join([
        f"采购申请 {request.request_no} 的后续采购流程：",
        *[
            _format_purchase_request_stage(stage)
            for stage in stages
        ],
    ])
    sources.extend(trace_sources)
    snapshot = AIContextSnapshot(
        object_type="purchase_request", object_id=request.id,
        title=f"采购申请 {request.request_no}", reference_no=request.request_no,
        status=request.status, summary=summary, source_records=sources,
        suggested_questions=["关联询价与报价进展如何？", "采购订单到货和验收进展如何？", "当前流程卡在哪个环节？"],
    )
    return snapshot, flow_answer, sources, request, stages


def _format_purchase_request_stage(stage: dict) -> str:
    if stage["status"] == "NO_PERMISSION":
        return f"- {stage['stage']}：{stage.get('summary') or '当前账号无读取权限，无法核验'}。"
    records = stage.get("records") or []
    if not records:
        return f"- {stage['stage']}：{stage.get('summary') or '没有查到关联记录'}。"
    if stage["stage"] == "询价与报价":
        entries = []
        for record in records[:8]:
            details = [f"报价 {record.get('quote_count', 0)} 条"]
            if record.get("comparison_status"):
                details.append(f"比价状态 {record['comparison_status']}")
            entries.append(f"{record['number']}（{record['status']}；{'，'.join(details)}）")
        return "- 询价与报价：" + "、".join(entries) + "。"
    return format_stage_line(stage)


def _purchase_request_answer(question: str, purchase_request: object, full_answer: str) -> str:
    """只回答申请数据中可直接核验的字段，不把字段摘要包装成审批分析。"""
    if any(marker in question for marker in ("状态", "审批")):
        answer = f"采购申请 {purchase_request.request_no} 当前状态：{purchase_request.status}。"
        if "审批" in question:
            answer += "当前读取的是申请状态字段，不包含审批节点或审批意见。"
        return answer
    if any(marker in question for marker in ("明细", "物料", "用途")):
        lines = [f"采购申请 {purchase_request.request_no}", f"采购用途：{purchase_request.purpose}", "采购明细："]
        if purchase_request.items:
            lines.extend(
                f"第 {item.line_no} 行：{item.requested_name}，数量 {item.quantity}，单位编号 #{item.unit_id}"
                for item in purchase_request.items
            )
        else:
            lines.append("当前没有采购明细。")
        return "\n".join(lines)
    if any(marker in question for marker in ("预算", "到货", "日期", "金额")):
        budget = (f"{format_amount(purchase_request.budget_amount)} {purchase_request.currency_code}"
                  if purchase_request.budget_amount is not None else "未填写")
        expected = purchase_request.expected_date.isoformat() if purchase_request.expected_date else "未填写"
        return f"采购申请 {purchase_request.request_no}\n预算金额：{budget}\n期望到货日期：{expected}"
    if any(marker in question for marker in ("缺", "还要", "完善")):
        return "当前已接入采购流程关联追踪；申请缺项判断规则尚未接入，不能据此判断资料是否齐全。\n" + full_answer
    return full_answer


def _delivery_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取当前用户可见的到货单，并返回确定性收货摘要及来源。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "warehouse.deliveries.read" not in permissions:
        raise AuthorizationError("当前账号没有到货单读取权限")

    delivery = delivery_service.get_delivery(db, user, object_id)
    order = read_order(db, user, delivery.po_id)
    dates = {
        "发运日期": delivery.shipment_date,
        "预计到货日期": delivery.expected_arrival_date,
        "实际到货日期": delivery.actual_arrival_date,
    }
    summary = [f"到货状态：{delivery.status}"]
    summary.extend(f"{label}：{value.isoformat() if value else '未登记'}" for label, value in dates.items())
    summary.append(f"到货明细：{len(delivery.items)} 行")
    summary.append(
        f"单证齐全：{sum(bool(item.document_complete) for item in delivery.items)}/{len(delivery.items)} 行"
    )
    sources = [
        {"dataset": "deliveries", "record_id": delivery.id, "label": f"到货单 {delivery.delivery_no}"},
        {"dataset": "purchase_orders", "record_id": order.id, "label": f"采购订单 {order.po_no}"},
        *[
            {"dataset": "delivery_items", "record_id": item.id, "label": f"到货明细第 {item.line_no} 行"}
            for item in delivery.items
        ],
    ]
    snapshot = AIContextSnapshot(
        object_type="delivery",
        object_id=delivery.id,
        title=f"到货单 {delivery.delivery_no}",
        reference_no=delivery.delivery_no,
        status=delivery.status,
        summary=summary,
        source_records=sources,
        suggested_questions=[
            "这张到货单收货进展如何？",
            "到货明细的短交数量是多少？",
            "到货单证是否齐全？",
        ],
    )
    return snapshot, {"delivery": delivery, "order": order, "source_records": sources}


def _delivery_answer(delivery: object, order: object) -> str:
    """只根据到货单当前字段回答，不推断质检或入库状态。"""
    receipt_status = "已确认收货" if delivery.status == "RECEIVED" else (
        "尚未确认收货" if delivery.status == "IN_TRANSIT" else f"当前状态为 {delivery.status}"
    )
    lines = [
        f"到货单 {delivery.delivery_no}：{receipt_status}。",
        f"关联采购订单 {order.po_no}；供应商 ID：{delivery.supplier_id}。",
        f"发运日期：{delivery.shipment_date.isoformat() if delivery.shipment_date else '未登记'}；"
        f"预计到货日期：{delivery.expected_arrival_date.isoformat() if delivery.expected_arrival_date else '未登记'}；"
        f"实际到货日期：{delivery.actual_arrival_date.isoformat() if delivery.actual_arrival_date else '未登记'}。",
    ]
    if delivery.logistics_company or delivery.tracking_no:
        lines.append(
            f"物流：{delivery.logistics_company or '未登记'}；运单号：{delivery.tracking_no or '未登记'}。"
        )
    if delivery.received_at:
        lines.append(f"收货时间：{delivery.received_at.isoformat()}。")
    if delivery.items:
        lines.append("到货明细：")
        lines.extend(
            f"第 {item.line_no} 行：计划 {item.planned_quantity}，实收 {item.actual_quantity}，"
            f"短交 {item.short_quantity}，单位编号 #{item.unit_id}，"
            f"批次 {item.batch_no or '未登记'}，单证{'齐全' if item.document_complete else '未齐全'}。"
            for item in delivery.items
        )
    else:
        lines.append("当前没有到货明细。")
    lines.append("本回答仅反映到货与收货记录，不代表质量验收或库存入库已完成。")
    return "\n".join(lines)


def _inventory_balance_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取有仓库范围权限的库存余额及其产品、批次等权威信息。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "warehouse.inventory.read" not in permissions:
        raise AuthorizationError("当前账号没有库存读取权限")

    balance = inventory_service.get_balance_for_user(db, user, object_id)
    product = db.get(Product, balance.product_id)
    warehouse = db.get(Warehouse, balance.warehouse_id)
    location = db.get(WarehouseLocation, balance.location_id)
    batch = db.get(InventoryBatch, balance.batch_id)
    unit = db.get(Unit, balance.unit_id)
    product_name = product.product_name if product else f"产品 #{balance.product_id}"
    batch_no = batch.batch_no if batch else f"批次 #{balance.batch_id}"
    unit_name = unit.unit_name if unit else f"单位 #{balance.unit_id}"
    summary = [
        f"产品：{product_name}",
        f"库存数量：{balance.quantity} {unit_name}",
        f"已锁定数量：{balance.locked_quantity} {unit_name}",
        f"仓库状态：{'可用' if balance.status == 'AVAILABLE' else '冻结' if balance.status == 'FROZEN' else balance.status}",
    ]
    if warehouse:
        summary.append(f"仓库：{warehouse.warehouse_name}（{warehouse.warehouse_code}）")
    if location:
        summary.append(f"库位：{location.location_name}（{location.location_code}）")
    if batch:
        summary.append(f"批次：{batch_no}")
        summary.append(f"有效期：{batch.expiry_date.isoformat() if batch.expiry_date else '未登记'}")
    sources = [{"dataset": "inventory_balances", "record_id": balance.id, "label": f"库存余额 #{balance.id}"}]
    if batch:
        sources.append({"dataset": "inventory_batches", "record_id": batch.id, "label": f"库存批次 {batch_no}"})
    snapshot = AIContextSnapshot(
        object_type="inventory_balance", object_id=balance.id,
        title=f"库存余额 #{balance.id}：{product_name}", status=balance.status,
        summary=summary, source_records=sources,
        suggested_questions=["这笔库存余额有多少可用量？", "这个批次何时到期？", "这笔库存当前是什么状态？"],
    )
    return snapshot, {"balance": balance, "batch": batch, "product_name": product_name, "batch_no": batch_no, "unit_name": unit_name}


def _inventory_balance_answer(trace: dict) -> str:
    balance = trace["balance"]
    status = "可用" if balance.status == "AVAILABLE" else "冻结" if balance.status == "FROZEN" else balance.status
    available_quantity = balance.quantity - balance.locked_quantity if balance.status == "AVAILABLE" else 0
    batch = trace["batch"]
    expiry_date = batch.expiry_date.isoformat() if batch and batch.expiry_date else "未登记"
    return "\n".join([
        f"库存余额 #{balance.id}：{trace['product_name']}，仓库状态为{status}。",
        f"库存数量：{balance.quantity} {trace['unit_name']}；已锁定数量：{balance.locked_quantity} {trace['unit_name']}；可用数量：{available_quantity} {trace['unit_name']}。",
        f"批次：{trace['batch_no']}；有效期：{expiry_date}。",
        "可用数量沿用库存查询口径：冻结余额计为 0，可用余额按库存数量减去已锁定数量计算；本回答只反映当前余额与批次记录。",
    ])


def _quality_acceptance_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取当前用户可见的质量验收记录、关联到货及已保存的检测结果。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "quality.acceptances.read" not in permissions:
        raise AuthorizationError("当前账号没有质量验收读取权限")

    acceptance = quality_acceptance_service.get_acceptance(db, user, object_id)
    delivery = db.get(Delivery, acceptance.delivery_id)
    status_labels = {
        "PENDING": "待验收",
        "REINSPECTION": "待复检",
        "PASSED": "合格",
        "PARTIAL": "部分合格",
        "FAILED": "不合格",
    }
    status_label = status_labels.get(acceptance.result, acceptance.result)
    items = list(delivery.items) if delivery else []
    item_by_id = {str(item.id): item for item in items}
    source_records = [{
        "dataset": "quality_acceptances", "record_id": acceptance.id,
        "label": f"质量验收 {acceptance.acceptance_no}",
    }]
    if delivery:
        source_records.append({
            "dataset": "deliveries", "record_id": delivery.id,
            "label": f"到货单 {delivery.delivery_no}",
        })
        source_records.extend({
            "dataset": "delivery_items", "record_id": item.id,
            "label": f"到货明细第 {item.line_no} 行",
        } for item in items)

    summary = [
        f"验收结果：{status_label}",
        f"质量证明文件：{'齐全' if acceptance.certificate_complete else '未齐全'}",
        f"检测报告：{'已登记' if acceptance.report_file_id else '未登记'}",
        f"检验时间：{acceptance.inspection_time.isoformat() if acceptance.inspection_time else '未登记'}",
        f"验收结论：{acceptance.conclusion or '未填写'}",
    ]
    if delivery:
        summary.append(f"关联到货单：{delivery.delivery_no}")
    if items:
        summary.append(f"关联到货明细：{len(items)} 行")
    snapshot = AIContextSnapshot(
        object_type="quality_acceptance", object_id=acceptance.id,
        title=f"质量验收 {acceptance.acceptance_no}", reference_no=acceptance.acceptance_no,
        status=acceptance.result, summary=summary, source_records=source_records,
        suggested_questions=["这张验收单的检测结果是什么？", "验收结论和质量证明文件状态如何？", "关联到货单有哪些检测明细？"],
    )
    return snapshot, {"acceptance": acceptance, "delivery": delivery, "items": item_by_id, "status_label": status_label}


def _quality_acceptance_answer(trace: dict) -> str:
    acceptance = trace["acceptance"]
    delivery = trace["delivery"]
    lines = [
        f"质量验收 {acceptance.acceptance_no}：{trace['status_label']}。",
        f"关联到货单：{delivery.delivery_no if delivery else '记录不可用'}。",
        f"质量证明文件：{'齐全' if acceptance.certificate_complete else '未齐全'}；"
        f"检测报告：{'已登记' if acceptance.report_file_id else '未登记'}。",
        f"检验时间：{acceptance.inspection_time.isoformat() if acceptance.inspection_time else '未登记'}。",
        f"验收结论：{acceptance.conclusion or '未填写'}。",
    ]
    result = acceptance.test_result
    if isinstance(result, dict) and isinstance(result.get("by_delivery_item"), dict):
        for item_id, tests in result["by_delivery_item"].items():
            item = trace["items"].get(str(item_id))
            line_no = item.line_no if item else f"明细 #{item_id}"
            if isinstance(tests, dict) and tests:
                values = "、".join(f"{name}：{value}" for name, value in tests.items())
                lines.append(f"检测结果：第 {line_no} 行 {values}。")
    elif isinstance(result, dict) and result:
        values = "、".join(f"{name}：{value}" for name, value in result.items())
        lines.append(f"检测结果：{values}。")
    elif isinstance(result, list) and result:
        lines.extend(f"检测结果：{entry}。" for entry in result)
    else:
        lines.append("当前未登记检测结果。")
    lines.append("本回答只复述已保存的验收记录，不根据报告内容或检测标准重新判定合格与否。")
    return "\n".join(lines)


def _finance_reconciliation_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取当前用户可见的对账单及发票、付款状态汇总。"""
    reconciliation = finance_service.get_reconciliation(db, user, object_id)
    from app.modules.ai.finance_read_model import read_reconciliation

    read_model = read_reconciliation(db, user, reconciliation)
    supplier = db.get(Supplier, reconciliation.supplier_id)
    invoice_summary = read_model["invoices"]
    payment_summary = read_model["payments"]
    payment_precheck = read_model["payment_precheck"]
    summary = [
        f"对账状态：{reconciliation.status}",
        f"对账金额：{format_amount(reconciliation.total_amount)} {reconciliation.currency_code}",
        f"发票状态汇总：{len(invoice_summary)} 种状态，{sum(int(row['count']) for row in invoice_summary)} 张",
        f"付款状态汇总：{len(payment_summary)} 种状态，{sum(int(row['count']) for row in payment_summary)} 笔",
        f"当前付款理论上限：{format_amount(payment_precheck['max_new_payment_amount'])} {reconciliation.currency_code}",
    ]
    summary.extend(
        f"第 {line['line_no']} 行 {line['product_name']}：验收 {format_decimal(line['accepted_quantity'])}，"
        f"对账 {format_decimal(line['reconciliation_quantity'])} {line['unit_name']}；"
        f"发票已核验 {format_amount(line['verified_invoice_amount'])}/"
        f"{format_amount(line['amount_incl_tax'])} {reconciliation.currency_code}。"
        for line in read_model["lines"]
    )
    if read_model["source_changed"]:
        summary.append("对账来源已变化，当前明细反映保存版本。")
    summary.extend(read_model["line_warnings"])
    if read_model["unallocated_invoices"]:
        summary.append("有效发票尚未行级匹配：" + "、".join(read_model["unallocated_invoices"]))
    if supplier:
        summary.append(f"供应商：{supplier.supplier_name}（{supplier.supplier_code}）")
    source_records = [{
        "dataset": "finance_reconciliations", "record_id": reconciliation.id,
        "label": f"财务对账单 {reconciliation.reconciliation_no}",
    }]
    snapshot = AIContextSnapshot(
        object_type="finance_reconciliation", object_id=reconciliation.id,
        title=f"财务对账单 {reconciliation.reconciliation_no}",
        reference_no=reconciliation.reconciliation_no, status=reconciliation.status,
        summary=summary, source_records=source_records + [{
            "dataset": "finance_reconciliation_items", "record_id": line["reconciliation_item_id"],
            "label": f"对账明细第 {line['line_no']} 行",
        } for line in read_model["lines"]],
        suggested_questions=["这张对账单目前是什么状态？", "发票和付款分别进展到哪一步？", "对账金额是多少？"],
    )
    return snapshot, {"reconciliation": reconciliation, "supplier": supplier, "read_model": read_model}


def _supplier_context(db: Session, user: User, object_id: int) -> tuple[AIContextSnapshot, dict]:
    """读取有供应商主数据权限的合作信息。"""
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if "SYS_ADMIN" not in roles and "master.suppliers.read" not in permissions:
        raise AuthorizationError("当前账号没有供应商读取权限")

    supplier = supplier_service.get_supplier(db, object_id)
    summary = [
        f"供应商状态：{supplier.status}",
        f"所在地区：{supplier.region or '未登记'}",
        f"经营范围：{supplier.business_scope or '未登记'}",
        f"合作等级：{supplier.cooperation_level or '未登记'}",
        f"付款条件：{supplier.payment_terms or '未登记'}",
        f"默认交货天数：{supplier.default_lead_days if supplier.default_lead_days is not None else '未登记'}",
    ]
    snapshot = AIContextSnapshot(
        object_type="supplier", object_id=supplier.id,
        title=f"供应商 {supplier.supplier_name}", reference_no=supplier.supplier_code,
        status=supplier.status, summary=summary,
        source_records=[{"dataset": "suppliers", "record_id": supplier.id,
                         "label": f"供应商 {supplier.supplier_code}"}],
        suggested_questions=["这家供应商的合作状态和等级是什么？", "供应商经营范围是什么？", "默认交货天数和付款条件是什么？"],
    )
    return snapshot, {"supplier": supplier}


def _finance_reconciliation_answer(trace: dict) -> str:
    reconciliation = trace["reconciliation"]
    supplier = trace["supplier"]
    read_model = trace["read_model"]
    lines = [
        f"财务对账单 {reconciliation.reconciliation_no}：{reconciliation.status}。",
        f"对账金额：{format_amount(reconciliation.total_amount)} {reconciliation.currency_code}。",
        f"供应商：{supplier.supplier_name if supplier else '未登记'}。",
    ]
    for label, rows in (("发票", read_model["invoices"]), ("付款", read_model["payments"])):
        detail = "、".join(f"{row['status']} {row['count']} 笔 / {format_amount(row['amount'])} {reconciliation.currency_code}" for row in rows) or "暂无记录"
        lines.append(f"{label}状态汇总：{detail}。")
    for row in read_model["lines"]:
        lines.append(
            f"第 {row['line_no']} 行 {row['product_name']}：订购 {format_decimal(row['ordered_quantity'])}，"
            f"已收 {format_decimal(row['received_quantity'])}，验收 {format_decimal(row['accepted_quantity'])}，"
            f"退货 {format_decimal(row['returned_quantity'])}，"
            f"对账 {format_decimal(row['reconciliation_quantity'])} {row['unit_name']}；"
            f"发票已占用 {format_amount(row['invoiced_reserved_amount'])}，"
            f"已核验 {format_amount(row['verified_invoice_amount'])}/"
            f"{format_amount(row['amount_incl_tax'])} {reconciliation.currency_code}。"
        )
        lines.extend(f"第 {row['line_no']} 行核查提示：{warning}。" for warning in row["warnings"])
    if read_model["source_changed"]:
        lines.append("订单、到货或退货来源与对账保存版本相比已变化，请按当前财务页面核对版本。")
    lines.extend(f"对账核查提示：{warning}。" for warning in read_model["line_warnings"])
    if read_model["unallocated_invoices"]:
        lines.append("有效发票尚未行级匹配：" + "、".join(read_model["unallocated_invoices"]) + "。")
    precheck = read_model["payment_precheck"]
    lines.append(
        f"付款前置数据：已核验发票 {format_amount(precheck['verified_invoice_amount'])} {reconciliation.currency_code}，"
        f"有效付款占用 {format_amount(precheck['active_payment_amount'])} {reconciliation.currency_code}，"
        f"当前单笔付款理论上限 {format_amount(precheck['max_new_payment_amount'])} {reconciliation.currency_code}。"
    )
    lines.extend(f"付款前置条件未满足：{blocker}。" for blocker in precheck["blockers"])
    lines.append(precheck["limitation"])
    lines.append("本回答复述系统保存的对账和匹配数据，不替代人工复核或付款服务的提交、审批校验。")
    return "\n".join(lines)


def _supplier_answer(trace: dict) -> str:
    supplier = trace["supplier"]
    return "\n".join([
        f"供应商 {supplier.supplier_code}：{supplier.supplier_name}，状态为{supplier.status}。",
        f"地区：{supplier.region or '未登记'}；经营范围：{supplier.business_scope or '未登记'}。",
        f"合作等级：{supplier.cooperation_level or '未登记'}；付款条件：{supplier.payment_terms or '未登记'}。",
        f"默认交货天数：{supplier.default_lead_days if supplier.default_lead_days is not None else '未登记'}。",
        "本回答仅复述供应商主数据，不包含履约绩效或风险判断。",
    ])


def resolve_context(db: Session, user: User, request: AIContextAskRequest) -> tuple[AIContextSnapshot, dict]:
    """按页面对象类型读取当前用户可见的业务上下文。"""
    if request.context.object_type == "purchase_order":
        return _purchase_order_snapshot(db, user, request.context.object_id)
    if request.context.object_type == "purchase_request":
        snapshot, answer, sources, purchase_request, stages = _purchase_request_context(db, user, request.context.object_id)
        return snapshot, {"answer": answer, "source_records": sources, "context_type": "purchase_request", "request": purchase_request, "stages": stages}
    if request.context.object_type == "delivery":
        snapshot, trace = _delivery_context(db, user, request.context.object_id)
        return snapshot, {**trace, "context_type": "delivery"}
    if request.context.object_type == "inventory_balance":
        snapshot, trace = _inventory_balance_context(db, user, request.context.object_id)
        return snapshot, {**trace, "context_type": "inventory_balance"}
    if request.context.object_type == "quality_acceptance":
        snapshot, trace = _quality_acceptance_context(db, user, request.context.object_id)
        return snapshot, {**trace, "context_type": "quality_acceptance"}
    if request.context.object_type == "finance_reconciliation":
        snapshot, trace = _finance_reconciliation_context(db, user, request.context.object_id)
        return snapshot, {**trace, "context_type": "finance_reconciliation"}
    if request.context.object_type == "supplier":
        snapshot, trace = _supplier_context(db, user, request.context.object_id)
        return snapshot, {**trace, "context_type": "supplier"}
    raise BusinessValidationError("当前页面对象暂不支持 AI 上下文问答，请使用已接入的详情页或 AI 工作台")


def ask_context(db: Session, user: User, request: AIContextAskRequest) -> AIContextAskResponse:
    """返回已授权对象的确定性答案；不调用模型，避免把页面对象误当成业务事实。"""
    snapshot, trace = resolve_context(db, user, request)
    if snapshot.object_type == "purchase_request":
        return AIContextAskResponse(
            answer=_purchase_request_answer(request.question, trace["request"], trace["answer"]), context=snapshot,
            citations=[{"type": "purchase-request-trace", "source_records": trace["source_records"], "stages": trace["stages"]}],
            model="purchase-request-trace",
        )
    if snapshot.object_type == "delivery":
        delivery = trace["delivery"]
        return AIContextAskResponse(
            answer=_delivery_answer(delivery, trace["order"]),
            context=snapshot,
            citations=[{"type": "delivery-context", "source_records": trace["source_records"]}],
            model="delivery-context",
        )
    if snapshot.object_type == "inventory_balance":
        return AIContextAskResponse(
            answer=_inventory_balance_answer(trace),
            context=snapshot,
            citations=[{"type": "inventory-balance-context", "source_records": snapshot.source_records}],
            model="inventory-balance-context",
        )
    if snapshot.object_type == "quality_acceptance":
        return AIContextAskResponse(
            answer=_quality_acceptance_answer(trace), context=snapshot,
            citations=[{"type": "quality-acceptance-context", "source_records": snapshot.source_records}],
            model="quality-acceptance-context",
        )
    if snapshot.object_type == "finance_reconciliation":
        return AIContextAskResponse(
            answer=_finance_reconciliation_answer(trace), context=snapshot,
            citations=[{"type": "finance-reconciliation-context", "source_records": snapshot.source_records}],
            model="finance-reconciliation-context",
        )
    if snapshot.object_type == "supplier":
        return AIContextAskResponse(
            answer=_supplier_answer(trace), context=snapshot,
            citations=[{"type": "supplier-context", "source_records": snapshot.source_records}],
            model="supplier-context",
        )
    return AIContextAskResponse(
        answer=_answer_for_question(request.question, trace),
        context=snapshot,
        citations=[{
            "type": "order_trace",
            "po_no": snapshot.reference_no,
            "source_records": snapshot.source_records,
            "order_trace": trace,
        }],
        model="order-trace",
    )


def ask_order_list(db: Session, user: User, request):
    """按当前用户权限和列表筛选条件重新查询，返回有限且可核验的订单事实。"""
    from datetime import date
    from app.modules.purchase_orders import service as order_service
    roles = set(get_user_role_codes(db, user.id))
    permissions = set(get_user_permission_codes(db, user.id))
    if 'SYS_ADMIN' not in roles and 'procurement.orders.read' not in permissions:
        raise AuthorizationError('没有采购订单读取权限')
    filters = request.filters
    orders, total = order_service.list_orders(db, user, keyword=filters.keyword, status=filters.status, page=1, page_size=100)
    sources = [{'dataset': 'purchase_orders', 'record_id': order.id, 'label': f'采购订单 {order.po_no}'} for order in orders]
    scope = f"筛选条件：订单编号包含 {filters.keyword or '不限'}；状态 {filters.status or '不限'}。"
    lines = [scope, f'当前账号范围内共有 {total} 条订单，本次读取 {len(orders)} 条。']
    if total > len(orders):
        lines.append('结果已截断，仅展示前 100 条；不能据此判断全部订单。')
    if not orders:
        lines.append('当前范围没有匹配订单。')
    else:
        lines.append('可见订单：')
        lines.extend(f"- {order.po_no}：状态 {order.status}，预计到货 {order.expected_arrival_date.isoformat() if order.expected_arrival_date else '未填写'}" for order in orders)
    active = [order for order in orders if order.status not in {'COMPLETED', 'CANCELLED'}]
    past_due = [order for order in active if order.expected_arrival_date and order.expected_arrival_date < date.today()]
    no_date = [order for order in active if order.expected_arrival_date is None]
    lines.append(f"需关注：本次读取的未完成订单中，预计到货日期已过 {len(past_due)} 条，未填预计到货日期 {len(no_date)} 条。")
    lines.append('日期提示不代表实际逾期或审批异常；未核验审批、履约及其他环节，不能作为完整风险判断。')
    return {'answer': '\n'.join(lines), 'context': {'object_type': 'purchase_order_list', 'object_id': None,
        'title': '采购订单列表', 'summary': [scope], 'source_records': sources,
        'suggested_questions': [], 'status': None, 'reference_no': None},
        'citations': [{'type': 'purchase-order-list', 'source_records': sources, 'total': total,
                       'returned': len(orders), 'truncated': total > len(orders)}],
        'model': 'order-list-context', 'provider': 'chemicalops'}
