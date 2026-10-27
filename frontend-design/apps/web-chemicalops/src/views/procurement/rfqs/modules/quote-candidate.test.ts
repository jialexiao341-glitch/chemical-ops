import type { RfqApi } from '#/api/procurement/rfqs';
import type { QuoteItemRow } from '../data';

import { describe, expect, it } from 'vitest';

import { replaceQuoteCandidate } from './quote-candidate';

const units = [{ label: 'kg', value: 1 }];
const base: QuoteItemRow[] = [{
  rfq_item_id: 10, requestedName: '乙醇', requestedQuantity: '100', unitName: 'kg',
  quoted_quantity: 100, unit_id: 1, moq_unit_id: 1,
}];
function candidate(overrides: Partial<RfqApi.QuoteParseCandidate> = {}): RfqApi.QuoteParseCandidate {
  return { file_id: 1, file_name: 'A.pdf', evidence: [], warnings: [], items: [], ...overrides };
}
const item: RfqApi.QuoteCandidateItem = {
  rfq_item_id: 10, source_location: '第1页', source_quote: '乙醇 100 kg 10',
  quoted_quantity: '100', unit_name: 'kg', unit_price: '10',
};

describe('quote candidate replacement', () => {
  it('replaces all document and line values on reimport, preserving only RFQ identity', () => {
    const first = replaceQuoteCandidate(base, candidate({
      currency_code: 'CNY', quote_date: '2026-10-01', valid_until: '2026-11-01', note: 'A',
      items: [{ ...item, supplier_model: 'A', tax_rate: '13', tax_included: true,
        lead_days: 7, payment_terms: '月结', moq_quantity: '20', moq_unit_name: 'kg',
        freight_amount: '5', freight_tax_rate: '9', freight_tax_included: true }],
    }), units);
    first.rows[0]!.note = 'manual';
    const second = replaceQuoteCandidate(first.rows, candidate({ file_id: 2, file_name: 'B.pdf' }), units);
    expect(second).toMatchObject({ sourceFileId: 2, supplierId: undefined, currencyCode: '',
      quoteDate: undefined, validUntil: undefined, note: '' });
    expect(second.rows).toEqual([{
      rfq_item_id: 10, requestedName: '乙醇', requestedQuantity: '100', unitName: 'kg',
      quoted_quantity: undefined, unit_id: undefined, unit_price: undefined,
      supplier_model: '', tax_rate: undefined, tax_basis: null, lead_days: undefined,
      payment_terms: '', moq_quantity: undefined, moq_unit_id: undefined,
      freight_amount: undefined, freight_tax_rate: undefined, freight_tax_basis: null, note: '',
    }]);
    expect(first.rows[0]!.unit_price).toBe(10);
  });

  it('does not choose either candidate when multiple lines bind to the same RFQ item', () => {
    const result = replaceQuoteCandidate(base, candidate({ items: [item, { ...item, unit_price: '99' }] }), units);
    expect(result.rows[0]!.unit_price).toBeUndefined();
    expect(result.rows[0]!.quoted_quantity).toBeUndefined();
    expect(result.warnings.join('')).toContain('重复');
  });

  it('clears unknown or missing quote and MOQ units instead of retaining RFQ units', () => {
    const result = replaceQuoteCandidate(base, candidate({ items: [{ ...item, unit_name: '桶', moq_unit_name: '箱' }] }), units);
    expect(result.rows[0]!.unit_id).toBeUndefined();
    expect(result.rows[0]!.moq_unit_id).toBeUndefined();
    expect(result.rows[0]!.unitName).toBe('kg');
  });

  it('accepts explicit zero, false and normalized units without matching unbound rows', () => {
    const result = replaceQuoteCandidate(base, candidate({ items: [{ ...item,
      unit_name: ' KG ', tax_rate: '0', tax_included: false, freight_amount: '0', freight_tax_included: false,
    }, { ...item, rfq_item_id: null, unit_price: '999' }] }), units);
    expect(result.rows[0]).toMatchObject({ unit_id: 1, unit_price: 10, tax_rate: 0,
      tax_basis: 'EXCLUDED', freight_amount: 0, freight_tax_basis: 'EXCLUDED' });
  });
});
