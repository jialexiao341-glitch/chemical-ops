"""页面对象上下文解析与只读 Copilot 回答。

页面只提交对象引用，本模块按当前用户重新读取业务对象、执行权限校验，
再基于既有订单追溯能力生成确定性回答；不接受客户端提交业务字段快照。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessValidationError
from app.modules.ai.order_trace import format_stage_line, trace_purchase_order
from app.modules.ai.schema import (
    AIContextAskRequest,
    AIContextAskResponse,
    AIContextSnapshot,
)
from app.modules.purchase_orders.service import get_order
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.purchase_requests.service import get_request as get_purchase_request
from app.modules.rfqs.model import RFQ
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User

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
        f"订单金额：{order.order_amount} {order.currency_code}",
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
    can_read_all_rfq = bool(roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"})
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
        if not can_read_all_rfq:
            rfq_query = rfq_query.where(RFQ.requester_id == user.id)
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
        summary.append(f"预算金额：{request.budget_amount} {request.currency_code}")
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
        budget = f"{purchase_request.budget_amount} {purchase_request.currency_code}" if purchase_request.budget_amount is not None else "未填写"
        expected = purchase_request.expected_date.isoformat() if purchase_request.expected_date else "未填写"
        return f"采购申请 {purchase_request.request_no}\n预算金额：{budget}\n期望到货日期：{expected}"
    if any(marker in question for marker in ("缺", "还要", "完善")):
        return "当前已接入采购流程关联追踪；申请缺项判断规则尚未接入，不能据此判断资料是否齐全。\n" + full_answer
    return full_answer


def resolve_context(db: Session, user: User, request: AIContextAskRequest) -> tuple[AIContextSnapshot, dict]:
    """按页面对象类型读取当前用户可见的业务上下文。"""
    if request.context.object_type == "purchase_order":
        return _purchase_order_snapshot(db, user, request.context.object_id)
    if request.context.object_type == "purchase_request":
        snapshot, answer, sources, purchase_request, stages = _purchase_request_context(db, user, request.context.object_id)
        return snapshot, {"answer": answer, "source_records": sources, "context_type": "purchase_request", "request": purchase_request, "stages": stages}
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
