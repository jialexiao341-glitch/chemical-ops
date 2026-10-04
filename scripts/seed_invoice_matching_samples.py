"""新增独立开发模拟发票链路；固定编号，重复运行不覆盖现有记录。"""

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.deliveries.model import Delivery, DeliveryItem
from app.modules.finance import service, invoice_matches
from app.modules.finance.model import FinanceInvoice, FinanceReconciliation, FinanceReconciliationItem
from app.modules.finance.schema import InvoiceCreate, InvoiceMatchSave
from app.modules.products.model import Product
from app.modules.purchase_orders.model import PurchaseOrder, PurchaseOrderItem
from app.modules.suppliers.model import Supplier
from app.modules.system.model import User

CASES = [('FULL', '全额匹配待复核'), ('SPLIT', '分两张发票开票'), ('MULTI', '一张发票匹配多个产品行'), ('AMOUNT', '匹配合计不符待处理'), ('TAX', '税额差异待说明'), ('REJECT', '驳回后重新录入')]
NOTE = '开发模拟：用于发票行匹配演示，非真实交易、验收或开票，不产生库存和资金流水。'
INVOICE_DATE = date(2026, 9, 30)
ORDER_DATE = INVOICE_DATE - timedelta(days=7)
ARRIVAL_DATE = INVOICE_DATE - timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if get_settings().app_env.lower() not in {'development', 'dev', 'test', 'testing', 'local'}:
        raise RuntimeError('仅允许在开发或测试环境生成模拟发票')
    if args.dry_run:
        print(json.dumps(CASES, ensure_ascii=False))
        return
    with SessionLocal() as db:
        clerk = db.scalar(select(User).where(User.username == 'finance_clerk'))
        manager = db.scalar(select(User).where(User.username == 'finance_manager'))
        supplier = db.scalar(select(Supplier).where(Supplier.status == 'ACTIVE').order_by(Supplier.id))
        products = list(db.scalars(select(Product).where(Product.status == 'ACTIVE').order_by(Product.id).limit(2)))
        if not clerk or not manager or not supplier or len(products) < 2:
            raise RuntimeError('请先准备财务账号、供应商和两个有效产品')
        manifest = []
        for code, label in CASES:
            po_no = f'PO-SIMINV-{code}'
            existing = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == po_no))
            if existing:
                rec = db.scalar(select(FinanceReconciliation).where(FinanceReconciliation.po_id == existing.id))
                if rec is None:
                    raise RuntimeError(f'{po_no} 已存在但缺少对账链路，请人工核查，脚本不覆盖')
                manifest.append({'case': label, 'po_no': po_no, 'order_id': existing.id, 'reconciliation_id': rec.id, 'reconciliation_no': rec.reconciliation_no})
                continue
            order = PurchaseOrder(po_no=po_no, supplier_id=supplier.id, buyer_id=clerk.id, department_id=clerk.department_id, order_amount=Decimal('2130'), currency_code='CNY', order_date=ORDER_DATE, expected_arrival_date=ARRIVAL_DATE, delivery_address='开发演示：研发园区收货区', status='COMPLETED', note=NOTE)
            db.add(order); db.flush()
            lines = []
            for number, (product, quantity, price, tax) in enumerate(zip(products, [10, 5], [100, 200], [13, 0]), 1):
                row = PurchaseOrderItem(po_id=order.id, line_no=number, product_id=product.id, product_name_snapshot=product.product_name, supplier_model_snapshot=product.model, planned_arrival_date=ARRIVAL_DATE, unit_id=product.unit_id, order_quantity=quantity, received_quantity=quantity, unit_price=price, tax_rate=tax)
                db.add(row); lines.append(row)
            db.flush()
            delivery = Delivery(delivery_no=f'DLV-SIMINV-{code}', po_id=order.id, supplier_id=supplier.id, shipment_date=ARRIVAL_DATE - timedelta(days=1), expected_arrival_date=ARRIVAL_DATE, actual_arrival_date=ARRIVAL_DATE, logistics_company='开发演示物流', tracking_no=f'DEMO-DLV-SIMINV-{code}', status='ACCEPTED', note=NOTE)
            db.add(delivery); db.flush()
            for row in lines:
                db.add(DeliveryItem(delivery_id=delivery.id, po_item_id=row.id, line_no=row.line_no, product_id=row.product_id, unit_id=row.unit_id, package_spec=products[row.line_no - 1].packaging_spec, planned_quantity=row.order_quantity, actual_quantity=row.order_quantity, batch_no=f'SIMINV-{code}-{row.line_no}'))
            db.flush()
            real_commit = db.commit
            db.commit = db.flush
            try:
                rec = service.create_reconciliation(db, clerk, order.id, NOTE)
                service.confirm_reconciliation(db, manager, rec.id, NOTE)
                basis = list(db.scalars(select(FinanceReconciliationItem).where(FinanceReconciliationItem.reconciliation_id == rec.id, FinanceReconciliationItem.version_no == rec.items_version).order_by(FinanceReconciliationItem.line_no)))
                def make(suffix, excl, tax, allocations):
                    inv = service.create_invoice(db, clerk, InvoiceCreate(reconciliation_id=rec.id, invoice_number=f'DEV-SIM-{code}-{suffix}', invoice_date=date(2026, 9, 30), amount_excl_tax=Decimal(excl), tax_amount=Decimal(tax), amount_incl_tax=Decimal(excl)+Decimal(tax), note=NOTE))
                    invoice_matches.save_match(db, clerk, inv.id, InvoiceMatchSave(reconciliation_version=rec.items_version, allocations=[{'reconciliation_item_id': basis[index].id, 'amount_excl_tax': amount, 'tax_amount': vat, 'difference_note': note} for index, amount, vat, note in allocations]))
                    return inv
                if code == 'SPLIT':
                    make('01', '500', '65', [(0, '500', '65', None)])
                    make('02', '1500', '65', [(0, '500', '65', None), (1, '1000', '0', None)])
                elif code == 'TAX':
                    make('01', '999', '131', [(0, '999', '131', None)])
                elif code == 'AMOUNT':
                    make('01', '1000', '130', [(0, '900', '117', None)])
                elif code == 'REJECT':
                    old = make('01', '1000', '130', [(0, '1000', '130', None)])
                    service.submit_invoice(db, clerk, old.id)
                    service.reject_invoice(db, manager, old.id, '开发模拟：票面需要更正，重新录入')
                    make('02', '1000', '130', [(0, '1000', '130', None)])
                else:
                    inv = make('01', '2000', '130', [(0, '1000', '130', None), (1, '1000', '0', None)])
                    if code == 'FULL':
                        service.submit_invoice(db, clerk, inv.id)
                manifest.append({'case': label, 'po_no': order.po_no, 'order_id': order.id, 'reconciliation_id': rec.id, 'reconciliation_no': rec.reconciliation_no})
            finally:
                db.commit = real_commit
        db.commit()
        samples = []
        for case in manifest:
            for inv in db.scalars(select(FinanceInvoice).where(FinanceInvoice.reconciliation_id == case['reconciliation_id']).order_by(FinanceInvoice.id)):
                samples.append({'场景': case['case'], '采购订单': case['po_no'], '对账单': case['reconciliation_no'], '发票记录': inv.invoice_no, '模拟发票号码': inv.invoice_number, '日期': inv.invoice_date.isoformat(), '币种': inv.currency_code, '不含税金额': str(inv.amount_excl_tax), '税额': str(inv.tax_amount), '价税合计': str(inv.amount_incl_tax), '状态': inv.status, '说明': NOTE})
    destination = ROOT / 'docs' / 'invoice-samples'
    destination.mkdir(exist_ok=True)
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    with (destination / '模拟发票清单.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
