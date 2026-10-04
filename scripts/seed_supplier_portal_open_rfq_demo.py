"""为本地供应商门户演示账号补充幂等的未截止询价样本。"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.products.model import Product  # noqa: E402
from app.modules.purchase_requests.model import Unit  # noqa: E402
from app.modules.rfqs.model import RFQ, RFQItem, RFQSupplier  # noqa: E402
from app.modules.supplier_portal.model import SupplierPortalAccount  # noqa: E402
from app.modules.suppliers.model import Supplier  # noqa: E402
from app.modules.system.model import User  # noqa: E402


SAMPLES = (
    ("RFQ-PORTAL-DEMO-01", "PRD-ETHANOL-AR", "乙醇 99% AR", "分析纯，随货提供 COA", 50, 7),
    ("RFQ-PORTAL-DEMO-02", "PRD-METHANOL-AR", "甲醇 AR", "分析纯，提供批次及有效期信息", 80, 12),
    ("RFQ-PORTAL-DEMO-03", "PRD-ACETONE-AR", "丙酮 AR", "分析纯，包装需密封完整", 40, 18),
)


def main() -> None:
    """创建或刷新仅面向 supplier_portal_demo 的演示询价。"""
    if get_settings().app_env.lower() not in {"development", "dev"}:
        raise RuntimeError("该演示数据脚本只允许在 development 环境运行")

    now = datetime.now()
    today = date.today()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "supplier_portal_demo", User.status == "ACTIVE"))
        if user is None:
            raise RuntimeError("找不到有效的 supplier_portal_demo 用户，请先运行演示账号种子脚本")
        account = db.scalar(
            select(SupplierPortalAccount).where(
                SupplierPortalAccount.user_id == user.id,
                SupplierPortalAccount.status == "ACTIVE",
            )
        )
        if account is None:
            raise RuntimeError("演示供应商用户没有有效供应商绑定")
        supplier = db.get(Supplier, account.supplier_id)
        buyer = db.scalar(select(User).where(User.username == "buyer", User.status == "ACTIVE"))
        if supplier is None or buyer is None:
            raise RuntimeError("演示供应商或采购员账号不存在")

        for rfq_no, product_code, fallback_name, requirements, quantity, deadline_days in SAMPLES:
            product = db.scalar(select(Product).where(Product.product_code == product_code, Product.status == "ACTIVE"))
            if product is None:
                raise RuntimeError(f"缺少演示物料 {product_code}，请先运行主数据种子脚本")
            unit = db.scalar(select(Unit).where(Unit.id == product.unit_id, Unit.status == "ACTIVE"))
            if unit is None:
                raise RuntimeError(f"演示物料 {product_code} 没有有效计量单位")

            rfq = db.scalar(select(RFQ).where(RFQ.rfq_no == rfq_no))
            if rfq is None:
                rfq = RFQ(rfq_no=rfq_no, requester_id=buyer.id)
                db.add(rfq)
            rfq.requester_id = buyer.id
            rfq.quote_deadline = now + timedelta(days=deadline_days)
            rfq.requested_delivery_date = today + timedelta(days=deadline_days + 14)
            rfq.delivery_requirements = "按询价要求送达，随货提供 COA、批次与有效期信息。"
            # RESPONDING 对应前端“报价中”状态；邀请仍保持 PENDING，供当前供应商实际体验报价流程。
            rfq.status = "RESPONDING"
            rfq.sent_at = rfq.sent_at or now - timedelta(days=1)
            rfq.closed_at = None
            db.flush()

            item = db.scalar(
                select(RFQItem).where(RFQItem.rfq_id == rfq.id, RFQItem.line_no == 1)
            )
            if item is None:
                item = RFQItem(rfq_id=rfq.id, line_no=1)
                db.add(item)
            item.product_id = product.id
            item.requested_name = product.product_name or fallback_name
            item.specification = product.model or "按产品规格供货"
            item.quantity = quantity
            item.unit_id = unit.id
            item.required_delivery_date = rfq.requested_delivery_date
            item.technical_requirements = requirements

            invitation = db.scalar(
                select(RFQSupplier).where(
                    RFQSupplier.rfq_id == rfq.id,
                    RFQSupplier.supplier_id == supplier.id,
                )
            )
            if invitation is None:
                db.add(
                    RFQSupplier(
                        rfq_id=rfq.id,
                        supplier_id=supplier.id,
                        response_status="PENDING",
                        invitation_channel="PORTAL",
                    )
                )

        db.commit()
        print(f"seeded_supplier={supplier.supplier_code}")
        print("seeded_rfqs=" + ",".join(sample[0] for sample in SAMPLES))
        print("all_quote_deadlines_in_days=" + ",".join(str(sample[-1]) for sample in SAMPLES))


if __name__ == "__main__":
    main()
