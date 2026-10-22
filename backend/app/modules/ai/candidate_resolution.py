"""Agent 与批次共用的候选契约；身份仍由当前授权工具重新核实。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError
from app.modules.ai.schema import PendingChoice


def validate_selection(pending: PendingChoice | None, *, entity: str, selected_id: int, revision: int) -> int:
    key = {'product': 'product_id', 'rfq_item': 'rfq_item_id'}.get(entity)
    if (pending is None or pending.entity != entity or pending.revision != revision or key is None
            or selected_id not in {row.get(key) for row in pending.candidates}):
        raise BusinessValidationError('选择必须来自本轮当前版本的待确认候选，请刷新后重选')
    return selected_id


def inventory_family(db: Session, rows: list[dict], keyword: str) -> bool:
    """同名规格或实际登记为同一有效化学品可汇总；不同化学品必须消歧。"""
    if not rows:
        return False
    if all(row.get("product_name") == keyword for row in rows):
        return True

    from app.modules.chemicals.model import Chemical
    from app.modules.products.model import Product

    identities = db.execute(
        select(Product.id, Product.chemical_id)
        .join(Chemical, Chemical.id == Product.chemical_id)
        .where(
            Product.id.in_([row["product_id"] for row in rows]),
            Chemical.status == "ACTIVE",
        )
    ).all()
    return len(identities) == len(rows) and len({row.chemical_id for row in identities}) == 1
