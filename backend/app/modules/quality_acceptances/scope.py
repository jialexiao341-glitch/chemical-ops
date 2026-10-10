"""质量验收的共享读取范围，供列表、来源和汇总查询使用。"""

from collections.abc import Collection

from sqlalchemy import select, true

from app.modules.deliveries.model import Delivery
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.scope import order_read_condition
from app.modules.quality_acceptances.model import QualityAcceptance
from app.modules.system.model import User


def acceptance_read_condition(user: User, roles: Collection[str]):
    if {"SYS_ADMIN", "PROCUREMENT_MANAGER", "QUALITY_MANAGER"}.intersection(roles):
        return true()
    if "QUALITY" in roles:
        return QualityAcceptance.inspector_id == user.id
    deliveries = select(Delivery.id).join(PurchaseOrder, PurchaseOrder.id == Delivery.po_id).where(
        order_read_condition(user, roles)
    )
    return QualityAcceptance.delivery_id.in_(deliveries)
