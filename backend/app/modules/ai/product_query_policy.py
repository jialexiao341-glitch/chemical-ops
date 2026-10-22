"""Agent 与批次共用的库存/报价查询前置策略。"""

from app.modules.ai.schema import Slots


def unsupported_product_slots(kind: str, slots: Slots) -> tuple[str, ...]:
    """返回库存/报价工具无法准确执行的已提供条件，防止调用方静默丢弃。"""
    if kind not in {"inventory", "quotes"}:
        return ()
    return tuple(name for name in ("date_from", "date_to", "unit") if getattr(slots, name) is not None)


def unsupported_product_slot_prompt(unsupported_slots: tuple[str, ...]) -> str:
    """为 Agent 与批次提供一致的执行前澄清文案。"""
    if not unsupported_slots:
        return ""
    labels = {"date_from": "起始日期", "date_to": "截止日期", "unit": "计量单位"}
    conditions = "、".join(dict.fromkeys(labels[slot] for slot in unsupported_slots if slot in labels))
    return (
        f"当前库存与报价工具不支持按指定{conditions}筛选。请确认是否按现有记录口径执行；"
        "库存按原始单位分别展示，不做单位换算。"
    )


def can_aggregate_inventory(
    *,
    total_rows: int,
    truncated: bool,
    explicit_aggregate: bool,
    same_product_family: bool,
) -> bool:
    """只允许完整多候选集合按明确全选或已验证的同产品族进行合计。"""
    if total_rows <= 1 or truncated:
        return False
    return explicit_aggregate or same_product_family
