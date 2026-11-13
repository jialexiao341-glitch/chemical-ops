import { describe, expect, it } from 'vitest';

import { buildActionProposalPlan, isActionProposalRoute } from './action-proposal-plan';

const allowAll = { hasCode: () => true, hasRole: () => false };
const denyAll = { hasCode: () => false, hasRole: () => false };

describe('action proposal plan', () => {
  it('recognizes all write proposal routes', () => {
    expect(isActionProposalRoute('purchase_order_submit')).toBe(true);
    expect(isActionProposalRoute('rfq_draft')).toBe(true);
    expect(isActionProposalRoute('agent')).toBe(false);
    expect(isActionProposalRoute('clarify')).toBe(false);
  });

  it('builds purchase_order.submit payload when po_no and permission exist', () => {
    const plan = buildActionProposalPlan(
      'purchase_order_submit',
      { slots: { po_no: 'PO-26001' } },
      allowAll,
    );
    expect(plan.ok).toBe(true);
    if (plan.ok) {
      expect(plan.actionType).toBe('purchase_order.submit');
      expect(plan.payload).toEqual({ po_no: 'PO-26001' });
    }
  });

  it('blocks unauthorized or missing-slot write routes before calling API', () => {
    const missingSlot = buildActionProposalPlan('purchase_submit', { slots: {} }, allowAll);
    expect(missingSlot).toEqual({
      kind: 'warning',
      message: '需要准确的采购申请编号，当前请求没有创建提案。',
      ok: false,
    });

    const forbidden = buildActionProposalPlan(
      'rfq_draft',
      { slots: { request_no: 'PR-26002' } },
      { hasCode: (codes) => codes[0] === 'procurement.rfqs.write', hasRole: () => false },
    );
    expect(forbidden).toEqual({
      kind: 'error',
      message: '创建询价提案需要询价写入和供应商读取权限。',
      ok: false,
    });

    const noOrderWrite = buildActionProposalPlan(
      'purchase_order_submit',
      { slots: { po_no: 'PO-26001' } },
      denyAll,
    );
    expect(noOrderWrite.ok).toBe(false);
  });

  it('requires positive quantity and reason for replenishment_draft', () => {
    const plan = buildActionProposalPlan(
      'replenishment_draft',
      { action_fields: { quantity: 100, reason: '安全库存不足' }, slots: { product_keyword: '乙醇', supplier_code: 'SUP-001' } },
      allowAll,
    );
    expect(plan.ok).toBe(true);
    if (plan.ok) {
      expect(plan.actionType).toBe('inventory.create_replenishment');
      expect(plan.payload).toEqual({
        product_keyword: '乙醇',
        quantity: 100,
        reason: '安全库存不足',
        supplier_code: 'SUP-001',
      });
    }
  });
});
