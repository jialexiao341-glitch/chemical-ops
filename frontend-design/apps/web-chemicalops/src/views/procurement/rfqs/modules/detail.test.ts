import { describe, expect, it } from 'vitest';

import { buildPurchaseOrderDraftPayload, purchaseOrderDraftPreview } from './order-draft-proposal';

describe('purchase order draft proposal preview', () => {
  it('sends only server-resolved comparison and selected quote identifiers', () => {
    expect(buildPurchaseOrderDraftPayload(71, 51)).toEqual({ comparison_id: 71, quote_id: 51 });
  });

  it('shows per-line terms and warnings from the versioned preview', () => {
    const preview = purchaseOrderDraftPreview({
      confirmation_id: 'a'.repeat(32), action_type: 'purchase_order.create_draft', resource_type: 'RFQ',
      resource_id: '14', preview_version: 1, diff: [],
      evidence: [{ type: 'purchase_order_terms_check', comparison_no: 'QC-071', quote_no: 'Q-051',
        items: [{ line_no: 1, product: '乙醇', quantity: '2', unit_id: 4, unit_price: '12.5',
          tax_rate: '13', currency_code: 'CNY', lead_days: 10, payment_terms: '月结30天',
          available_request_quantity: '2', required_delivery_date: '2026-11-10' }] }],
      warnings: ['尚未填写收货地址'], blockers: [], risk_level: 'MEDIUM', status: 'PENDING',
      expires_at: '2026-11-01T00:00:00Z', requires_user_confirmation: true,
    });

    expect(preview.comparisonNo).toBe('QC-071');
    expect(preview.quoteNo).toBe('Q-051');
    expect(preview.items[0]).toContain('月结30天');
    expect(preview.items[0]).toContain('申请剩余量 2');
    expect(preview.warnings).toEqual(['尚未填写收货地址']);
  });
});
