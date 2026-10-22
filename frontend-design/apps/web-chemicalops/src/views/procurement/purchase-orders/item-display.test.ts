import { describe, expect, it } from 'vitest';

import { paymentTermsSnapshotLabel } from './item-display';

describe('purchase order item payment terms snapshot', () => {
  it('makes absent historical snapshots explicit without reading the live quote', () => {
    expect(paymentTermsSnapshotLabel(null)).toBe('未留存快照');
    expect(paymentTermsSnapshotLabel(undefined)).toBe('未留存快照');
    expect(paymentTermsSnapshotLabel('月结 30 天')).toBe('月结 30 天');
    expect(paymentTermsSnapshotLabel('   ')).toBe('未留存快照');
  });
});
