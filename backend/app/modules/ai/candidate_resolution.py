"""Agent 与批次共用的候选契约；身份仍由当前授权工具重新核实。"""
from app.core.errors import BusinessValidationError
from app.modules.ai.schema import PendingChoice


def validate_selection(pending: PendingChoice | None, *, entity: str, selected_id: int, revision: int) -> int:
    key = {'product': 'product_id', 'rfq_item': 'rfq_item_id'}.get(entity)
    if (pending is None or pending.entity != entity or pending.revision != revision or key is None
            or selected_id not in {row.get(key) for row in pending.candidates}):
        raise BusinessValidationError('选择必须来自本轮当前版本的待确认候选，请刷新后重选')
    return selected_id
