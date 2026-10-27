import type { RfqApi } from '#/api/procurement/rfqs';
import type { QuoteItemRow } from '../data';

function numberOrEmpty(value: null | number | string | undefined) {
  if (value == null || String(value).trim() === '') return undefined;
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}

function taxBasis(value: boolean | null | undefined) {
  return value == null ? null : value ? 'INCLUDED' as const : 'EXCLUDED' as const;
}

/** Build a complete replacement without mutating the current form or carrying its values over. */
export function replaceQuoteCandidate(
  baseRows: QuoteItemRow[],
  candidate: RfqApi.QuoteParseCandidate,
  units: Array<{ label: string; value: number }>,
) {
  const warnings = [...candidate.warnings];
  const unitId = (name: null | string | undefined) => name?.trim()
    ? units.find((unit) => unit.label.trim().toLowerCase() === name.trim().toLowerCase())?.value
    : undefined;
  const rows: QuoteItemRow[] = baseRows.map((base) => {
    const matches = candidate.items.filter((item) => item.rfq_item_id != null && item.rfq_item_id === base.rfq_item_id);
    if (matches.length > 1) {
      warnings.push(`物料「${base.requestedName}」存在重复匹配候选，未自动填入，请人工核对原文。`);
    }
    const item = matches.length === 1 ? matches[0] : undefined;
    return {
      rfq_item_id: base.rfq_item_id,
      requestedName: base.requestedName,
      requestedQuantity: base.requestedQuantity,
      unitName: base.unitName,
      quoted_quantity: numberOrEmpty(item?.quoted_quantity),
      unit_id: unitId(item?.unit_name),
      unit_price: numberOrEmpty(item?.unit_price),
      supplier_model: item?.supplier_model ?? '',
      tax_rate: numberOrEmpty(item?.tax_rate),
      tax_basis: taxBasis(item?.tax_included),
      lead_days: numberOrEmpty(item?.lead_days),
      payment_terms: item?.payment_terms ?? '',
      moq_quantity: numberOrEmpty(item?.moq_quantity),
      moq_unit_id: unitId(item?.moq_unit_name),
      freight_amount: numberOrEmpty(item?.freight_amount),
      freight_tax_rate: numberOrEmpty(item?.freight_tax_rate),
      freight_tax_basis: taxBasis(item?.freight_tax_included),
      note: '',
    };
  });
  return {
    sourceFileId: candidate.file_id,
    supplierId: undefined,
    currencyCode: candidate.currency_code ?? '',
    quoteDate: candidate.quote_date ?? undefined,
    validUntil: candidate.valid_until ?? undefined,
    note: candidate.note ?? '',
    rows,
    warnings,
  };
}
