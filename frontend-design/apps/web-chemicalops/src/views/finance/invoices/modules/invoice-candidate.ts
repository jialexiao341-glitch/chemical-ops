export function candidateAmount(raw: null | string): { valid: boolean; value: null | number } {
  if (raw === null) return { valid: true, value: null };
  if (!/^\d+(?:\.\d{1,6})?$/.test(raw)) return { valid: false, value: null };
  const numeric = Number(raw);
  const [whole = '', decimals = ''] = raw.split('.');
  const canonical = `${whole.replace(/^0+(?=\d)/, '')}.${decimals.padEnd(6, '0')}`;
  if (!Number.isFinite(numeric) || numeric.toFixed(6) !== canonical) return { valid: false, value: null };
  return { valid: true, value: numeric };
}
