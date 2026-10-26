"""按授权订单事实准备交期跟进草稿；不发送、不修改业务记录。"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.errors import BusinessValidationError
from app.core.time import business_today
from app.modules.ai.formatting import format_decimal
from app.modules.purchase_orders import service
from app.modules.purchase_requests.model import Unit


class FollowupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    order_id: int = Field(gt=0)
    followup_note: str = Field(default="", max_length=1000)

    @field_validator("followup_note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        if value and not value.strip():
            raise ValueError("补充说明不能仅为空白")
        return value.strip()


def validate_input(payload: dict) -> FollowupInput:
    try:
        return FollowupInput.model_validate(payload)
    except ValidationError as exc:
        raise BusinessValidationError("请提供有效的订单 ID 和不超过 1000 字的补充说明，不能覆盖业务事实") from exc


def build_followup(db, user, order_id: int, *, note: str = "", for_update: bool = False) -> dict:
    data = validate_input({"order_id": order_id, "followup_note": note})
    order = service.get_order(db, user, data.order_id, for_update=for_update)
    if order.status not in {"ORDERED", "PARTIAL"}:
        raise BusinessValidationError("仅已下单或部分到货的订单可以准备交期跟进草稿")
    today = business_today()
    lines, messages = [], []
    for item in sorted(order.items, key=lambda item: item.line_no):
        unit = db.get(Unit, item.unit_id)
        unit_name = unit.unit_name if unit else f"单位#{item.unit_id}（名称未维护）"
        planned = item.planned_arrival_date or order.expected_arrival_date
        pending = max(item.order_quantity - item.received_quantity, 0)
        lines.append({
            "id": item.id, "line_no": item.line_no, "product": item.product_name_snapshot,
            "unit_id": item.unit_id, "unit_name": unit_name, "status": item.status,
            "ordered": format_decimal(item.order_quantity),
            "received": format_decimal(item.received_quantity), "pending": format_decimal(pending),
            "planned_arrival_date": item.planned_arrival_date.isoformat() if item.planned_arrival_date else None,
        })
        if pending <= 0:
            continue
        date_label = planned.isoformat() if planned else "未维护，请供应商反馈"
        if planned and planned < today:
            date_label += f"（已逾期 {(today - planned).days} 天）"
        messages.append(
            f"第 {item.line_no} 行 {item.product_name_snapshot}：订购 {format_decimal(item.order_quantity)} {unit_name}，"
            f"订单已收 {format_decimal(item.received_quantity)} {unit_name}，待收 {format_decimal(pending)} {unit_name}；"
            f"当前计划到货 {date_label}。"
        )
    if not messages:
        raise BusinessValidationError("当前订单没有待收数量，无需生成催办草稿")
    snapshot = {
        "order_id": order.id, "po_no": order.po_no, "supplier_id": order.supplier_id,
        "status": order.status, "business_date": today.isoformat(),
        "expected_arrival_date": order.expected_arrival_date.isoformat() if order.expected_arrival_date else None,
        "supplier_confirmed_at": order.supplier_confirmed_at.isoformat() if order.supplier_confirmed_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None, "items": lines,
    }
    message = "\n".join([
        "供应商您好：",
        f"请跟进采购订单 {order.po_no}。",
        f"截至上海业务日 {today.isoformat()}，订单供应商确认状态：{'已确认' if order.supplier_confirmed_at else '待确认'}。",
        f"订单当前预计到货日期：{snapshot['expected_arrival_date'] or '未维护'}。",
        *messages,
        "请核实待交付明细，反馈预计发货/到货日期及影响交期的原因；如已发货，请提供物流信息。",
        *([f"补充说明：{data.followup_note}"] if data.followup_note else []),
    ])
    return {
        "message": message, "snapshot": snapshot,
        "warnings": [
            "仅保存催办草稿，尚未向供应商发送；请由经办人核对后通过既有渠道联系。",
            "数量和交期来自订单主单及明细；未读取独立物流记录或供应商回复，不代表交期预测。",
        ],
    }
