"""Agent 与批次共用的候选契约；身份仍由当前授权工具重新核实。"""
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai_agent.schema import PendingChoice


def validate_selection(pending: PendingChoice | None, *, entity: str, selected_id: int, revision: int) -> int:
    """确认选择属于当前版本的候选集合；不匹配时要求重新选择。"""
    key = {'product': 'product_id', 'rfq_item': 'rfq_item_id'}.get(entity)
    if (pending is None or pending.entity != entity or pending.revision != revision or key is None
            or selected_id not in {row.get(key) for row in pending.candidates}):
        raise BusinessValidationError('选择必须来自本轮当前版本的待确认候选，请刷新后重选')
    return selected_id


def inventory_family(db: Session, rows: list[dict], keyword: str) -> bool:
    """只有同一产品（同一 product_id，即同规格）跨仓库可汇总；不同规格必须消歧。

    名称相同或登记为同一化学品都不构成合计依据：同名不同规格在库存上不可比，
    静默合计会让用户看到错误的可用量。显式全选仍由 aggregate_products 放行。
    """
    if not rows:
        return False
    ids = {row.get("product_id") for row in rows}
    return len(ids) == 1 and None not in ids
