"""业务事件到 Agent 待办的规则化建议。

扫描产生的异常按类型生成可执行建议，通过站内通知推送给责任角色；
前端把建议指令带入 AI 工作台，仍由用户决定是否发起提案。
"""

from __future__ import annotations

from app.modules.notifications.service import notify_users


_SUGGESTION_TYPES = {
    "INVOICE_DIFFERENCE": {
        "title": "发票匹配差异核查建议",
        "instruction": "核实发票与对账匹配差异并按财务流程处理，优先级 NORMAL，2 天内完成",
        "roles": ("FINANCE_MANAGER",),
    },
    "QUOTE_EXPIRED": {
        "title": "报价过期处理建议",
        "instruction": "核实过期报价并联系供应商更新报价，优先级 NORMAL，2 天内完成",
        "roles": ("PROCUREMENT_MANAGER",),
    },
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
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from app.modules.ai.model import AIOperationSuggestion
    if db.scalar(select(AIOperationSuggestion.id).where(AIOperationSuggestion.exception_id == exception.id)) is not None:
        return []
    try:
        with db.begin_nested():
            db.add(AIOperationSuggestion(exception_id=exception.id, title=suggestion['title'],
                content=suggestion['content'], instruction=suggestion['instruction'], status='OPEN'))
            db.flush()
    except IntegrityError:
        if db.scalar(select(AIOperationSuggestion.id).where(AIOperationSuggestion.exception_id == exception.id)) is not None:
            return []
        raise
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


def get_suggestion(db, user, suggestion_id, *, for_update=False):
    """同时按异常读取范围过滤，避免通过建议泄露异常。"""
    from sqlalchemy import select
    from app.core.errors import ResourceNotFoundError
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions.service import _exception_record_scope_condition
    statement = (select(AIOperationSuggestion).join(OperationException, OperationException.id == AIOperationSuggestion.exception_id)
                 .where(AIOperationSuggestion.id == suggestion_id, _exception_record_scope_condition(db, user)))
    if for_update:
        statement = statement.with_for_update()
    result = db.scalar(statement)
    if result is None:
        raise ResourceNotFoundError('运营建议不存在')
    return result


def list_suggestions(db, user, *, status, page, page_size):
    from sqlalchemy import func, select
    from app.modules.ai.model import AIOperationSuggestion
    from app.modules.operation_exceptions.model import OperationException
    from app.modules.operation_exceptions.service import _exception_record_scope_condition
    condition = _exception_record_scope_condition(db, user)
    base = select(AIOperationSuggestion).join(OperationException, OperationException.id == AIOperationSuggestion.exception_id).where(condition)
    if status:
        base = base.where(AIOperationSuggestion.status == status)
    total = db.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    rows = db.scalars(base.order_by(AIOperationSuggestion.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def suggestion_payload(db, item):
    from app.modules.operation_exceptions.model import OperationException
    exception = db.get(OperationException, item.exception_id)
    return {'id': item.id, 'exception_id': item.exception_id, 'exception_no': exception.exception_no,
            'title': item.title, 'content': item.content, 'instruction': item.instruction, 'exception_status': exception.status,
            'status': item.status, 'handled_by': item.handled_by, 'handled_at': item.handled_at,
            'task_id': item.task_id, 'created_at': item.created_at}


def transition_suggestion(db, user, suggestion_id, status):
    from datetime import datetime
    from app.core.errors import BusinessValidationError
    from app.modules.operation_exceptions import service as exception_service
    from app.modules.operation_exceptions.schema import OperationTaskCreate
    from app.modules.system.audit import add_audit_log
    if status not in {'IGNORED', 'CLOSED', 'HANDED_OFF'}:
        raise BusinessValidationError('无效的建议处理状态')
    item = get_suggestion(db, user, suggestion_id, for_update=True)
    if item.status != 'OPEN':
        raise BusinessValidationError('该建议已处理，请刷新状态')
    exception_service.get_exception_for_task_creation(db, user, item.exception_id)
    if status == 'HANDED_OFF':
        task = exception_service.create_task(db, user, item.exception_id,
            OperationTaskCreate(title=item.instruction[:255], assignee_id=user.id, priority='NORMAL'), commit=False)
        item.task_id = task.id
    item.status = status
    item.handled_by = user.id
    item.handled_at = datetime.now()
    add_audit_log(db, actor_id=user.id, action_type=status, resource_type='AI_OPERATION_SUGGESTION',
                  resource_id=item.id, request_summary='处理运营建议', result_status='SUCCESS')
    db.commit()
    db.refresh(item)
    return item
