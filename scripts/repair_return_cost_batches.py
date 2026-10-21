"""修复可唯一确定正确成本层的历史退货分摊；默认只预演并回滚。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select, text
from app.core.db import SessionLocal
from app.core.config import get_settings
from app.modules.inventory.model import InventoryBalance, InventoryTransaction
from app.modules.inventory_cost.model import InventoryCostAllocation, InventoryCostLayer
from app.modules.system.audit import add_audit_log
from app.modules.system.model import User, UserRole, Role


def repair(db, actor_id: int) -> list[dict]:
    bad = list(db.execute(select(InventoryCostAllocation, InventoryTransaction)
        .join(InventoryTransaction, InventoryTransaction.id == InventoryCostAllocation.transaction_id)
        .join(InventoryCostLayer, InventoryCostLayer.id == InventoryCostAllocation.cost_layer_id)
        .where(InventoryTransaction.batch_id != InventoryCostLayer.batch_id)
        .order_by(InventoryTransaction.created_at, InventoryCostAllocation.id)).all())
    if any(tx.source_type != "INVENTORY_RETURN" for _, tx in bad):
        raise RuntimeError("存在非退货跨批次分摊，必须核对下游成本传播，未执行自动修复")
    # 与在线写入一致先锁余额，再按固定 ID 顺序锁成本层/分摊。
    slots = sorted({(tx.warehouse_id, tx.location_id, tx.product_id, tx.batch_id, tx.unit_id) for _, tx in bad})
    for warehouse, location, product, batch, unit in slots:
        db.scalar(select(InventoryBalance).where(InventoryBalance.warehouse_id == warehouse,
            InventoryBalance.location_id == location, InventoryBalance.product_id == product,
            InventoryBalance.batch_id == batch, InventoryBalance.unit_id == unit).with_for_update())
    layers = list(db.scalars(select(InventoryCostLayer).order_by(InventoryCostLayer.id).with_for_update()).all()) if bad else []
    by_id = {layer.id: layer for layer in layers}
    reports = []
    for allocation, tx in bad:
        db.refresh(allocation, with_for_update=True)
        old = by_id[allocation.cost_layer_id]
        if old.batch_id == tx.batch_id:
            continue
        targets = [layer for layer in layers if
            (layer.warehouse_id, layer.location_id, layer.product_id, layer.batch_id, layer.unit_id) ==
            (tx.warehouse_id, tx.location_id, tx.product_id, tx.batch_id, tx.unit_id)
            and layer.created_at <= tx.created_at]
        if len(targets) != 1 or targets[0].currency_code != old.currency_code:
            raise RuntimeError(f"交易 {tx.id} 正确成本层或币种无法唯一确定，全部回滚")
        target = targets[0]
        if target.remaining_quantity < allocation.quantity or old.remaining_quantity + allocation.quantity > old.original_quantity:
            raise RuntimeError(f"交易 {tx.id} 成本数量无法安全恢复，全部回滚")
        report = {"allocation_id": allocation.id, "transaction_id": tx.id,
            "old_layer_id": old.id, "new_layer_id": target.id, "quantity": str(allocation.quantity),
            "old_cost": str(allocation.total_cost), "new_cost": str(allocation.quantity * target.unit_cost)}
        old.remaining_quantity += allocation.quantity
        target.remaining_quantity -= allocation.quantity
        allocation.cost_layer_id = target.id
        allocation.unit_cost = target.unit_cost
        allocation.total_cost = allocation.quantity * target.unit_cost
        add_audit_log(db, actor_id=actor_id, action_type="REPAIR_COST_ALLOCATION",
            resource_type="INVENTORY_TRANSACTION", resource_id=tx.id,
            request_summary=json.dumps(report, ensure_ascii=False), result_status="SUCCESS")
        reports.append(report)
    db.flush()
    if reports:
        differences = db.execute(text((ROOT / "database/checks/inventory_cost_quantities.sql").read_text(encoding="utf-8"))).all()
        if differences:
            raise RuntimeError("修复后仍有库存成本数量差异，全部回滚；需进一步核对历史数据")
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", default="tmp/return-cost-repair.json")
    args = parser.parse_args()
    if args.apply and get_settings().app_env.lower() in {"production", "prod"}:
        raise RuntimeError("生产历史成本修正需走财务复核流程，本工具仅允许预演")
    if args.apply:
        from migrate_database import _run_backup
        print(_run_backup())
    with SessionLocal() as db:
        # 独立维护脚本补全外键目标元数据，不导入或启动 Web 应用。
        from app.models.base import Base
        Base.metadata.reflect(bind=db.get_bind())
        actor_id = db.scalar(select(User.id).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
            .where(User.status == "ACTIVE", Role.role_code == "SYS_ADMIN", Role.status == "ACTIVE").order_by(User.id).limit(1))
        if actor_id is None:
            raise RuntimeError("缺少可记录审计的系统管理员")
        reports = repair(db, actor_id)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"applied": args.apply, "changes": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"return_cost_repairs={len(reports)} applied={args.apply} report={output}")


if __name__ == "__main__":
    main()
