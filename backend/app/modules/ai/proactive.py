"""业务事件到 Agent 待办的规则化建议。

扫描产生的异常按类型生成可执行建议，通过站内通知推送给责任角色；
前端把建议指令带入 AI 工作台，仍由用户决定是否发起提案。
"""

from __future__ import annotations

from app.modules.notifications.service import notify_users


_SUGGESTION_TYPES = {
    "LOW_STOCK": {
        "title": "低库存补货建议",
        "instruction": "核实产品低库存原因，并准备补货申请，优先级 HIGH，3 天内完成",
        "roles": ("WAREHOUSE", "PROCUREMENT_MANAGER"),
    },
    "OVERDUE": {
        "title": "逾期到货催办建议",
        "instruction": "联系供应商确认逾期到货的新交期，优先级 HIGH，2 天内完成",
        "roles": ("PROCUREMENT_MANAGER",),
    },
    "INVENTORY_EXPIRY": {
        "title": "临期库存处理建议",
        "instruction": "核实临期批次并制定处理方案，优先级 HIGH，3 天内完成",
        "roles": ("WAREHOUSE", "PROCUREMENT_MANAGER"),
    },
    "QUALITY_PENDING": {
        "title": "待验收催办建议",
        "instruction": "催办质量验收并确认缺项，优先级 NORMAL，1 天内完成",
        "roles": ("QUALITY", "QUALITY_MANAGER"),
    },
}


def build_exception_suggestion(exception) -> dict | None:
    """按异常类型生成建议；未知类型不生成，避免泛化打扰。"""

    config = _SUGGESTION_TYPES.get(str(exception.exception_type))
    if config is None:
        return None
    instruction = f"给异常 {exception.exception_no} 创建处理任务：{config['instruction']}。"
    content = (
        f"{exception.description}\n"
        f"建议：{config['title']}，由责任岗位核实后处理。\n"
        f"建议指令：{instruction}"
    )
    return {
        "title": f"运营建议：{config['title']}",
        "content": content,
        "instruction": instruction,
        "roles": config["roles"],
    }


def publish_exception_suggestion(db, exception) -> list:
    """对新建异常发送一条可带入 AI 工作台的建议通知；不单独提交事务。"""

    suggestion = build_exception_suggestion(exception)
    if suggestion is None:
        return []
    return notify_users(
        db,
        recipient_ids=[exception.owner_id] if exception.owner_id else (),
        role_codes=suggestion["roles"],
        notification_type="OPERATION_SUGGESTION",
        title=suggestion["title"],
        content=suggestion["content"],
        related_type="OPERATION_EXCEPTION",
        related_id=exception.id,
    )
