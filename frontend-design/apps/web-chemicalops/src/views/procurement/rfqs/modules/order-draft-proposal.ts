import type { AiApi } from '#/api/ai';

export const PURCHASE_ORDER_DRAFT_ACTION = 'purchase_order.create_draft';

export function buildPurchaseOrderDraftPayload(comparisonId: number, quoteId: number) {
  return { comparison_id: comparisonId, quote_id: quoteId };
}

export function purchaseOrderDraftPreview(
  proposal: AiApi.ActionProposalPreview,
  unitLabel: (unitId: number) => string = (unitId) => `#${unitId}`,
) {
  const evidence = proposal.evidence.find((item) => item.type === 'purchase_order_terms_check');
  const items = Array.isArray(evidence?.items) ? evidence.items : [];
  return {
    comparisonNo: typeof evidence?.comparison_no === 'string' ? evidence.comparison_no : '',
    quoteNo: typeof evidence?.quote_no === 'string' ? evidence.quote_no : '',
    supplierId: typeof evidence?.supplier_id === 'number' ? evidence.supplier_id : undefined,
    items: items.map((value) => {
      const item = value as Record<string, unknown>;
      return [
        `第 ${String(item.line_no ?? '-')} 行 ${String(item.product ?? '物料')}`,
        `数量 ${String(item.quantity ?? '-')} / 单位 ${typeof item.unit_id === 'number' ? unitLabel(item.unit_id) : '未提供'}`,
        `单价 ${String(item.unit_price ?? '-')} ${String(item.currency_code ?? '')}`,
        `税率 ${item.tax_rate == null ? '未提供' : `${String(item.tax_rate)}%`}`,
        `交期 ${item.lead_days == null ? '未提供' : `${String(item.lead_days)} 天`}`,
        `付款条件 ${String(item.payment_terms || '报价未提供')}`,
        `申请剩余量 ${String(item.available_request_quantity ?? '无法核对')}`,
        `要求到货 ${String(item.required_delivery_date ?? '未提供')}`,
      ].join('；');
    }),
    warnings: proposal.warnings,
  };
}
