"""页面对象上下文解析与只读 Copilot 回答。

页面只提交对象引用，本模块按当前用户重新读取业务对象、执行权限校验，
再基于既有订单追溯能力生成确定性回答；不接受客户端提交业务字段快照。
"""

from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai.order_trace import format_stage_line, trace_purchase_order
from app.modules.ai.schema import (
    AIContextAskRequest,
    AIContextAskResponse,
    AIContextSnapshot,
)
from app.modules.purchase_orders.service import get_order
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


def resolve_context(db: Session, user: User, request: AIContextAskRequest) -> tuple[AIContextSnapshot, dict]:
    """按页面对象类型解析上下文；当前首个切片仅开放采购订单详情页。"""
    if request.context.object_type == "purchase_order":
        return _purchase_order_snapshot(db, user, request.context.object_id)
    raise BusinessValidationError("当前页面对象暂不支持 AI 上下文问答，请使用订单详情页或 AI 工作台")


def ask_context(db: Session, user: User, request: AIContextAskRequest) -> AIContextAskResponse:
    """返回已授权对象的确定性答案；不调用模型，避免把页面对象误当成业务事实。"""
    snapshot, trace = resolve_context(db, user, request)
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
