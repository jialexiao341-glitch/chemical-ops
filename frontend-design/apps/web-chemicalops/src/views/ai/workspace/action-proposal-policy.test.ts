import { describe, expect, it } from 'vitest';

import { canConfirmActionProposal, shouldReplaceActionProposal } from './action-proposal-policy';

const proposal = (overrides = {}) => ({
  confirmation_id: 'a'.repeat(32),
  action_type: 'purchase_request.update_draft',
  preview_version: 2,
  blockers: [],
  status: 'PENDING',
  ...overrides,
});

describe('action proposal policy', () => {
  it('enables confirmation only for the current pending, unblocked preview', () => {
    expect(canConfirmActionProposal(proposal(), 2, false)).toBe(true);
    expect(canConfirmActionProposal(proposal(), 1, false)).toBe(false);
    expect(canConfirmActionProposal(proposal({ status: 'EXECUTED' }), 2, false)).toBe(false);
    expect(canConfirmActionProposal(proposal({ blockers: ['缺少明细'] }), 2, false)).toBe(false);
    expect(canConfirmActionProposal(proposal(), 2, true)).toBe(false);
  });

  it('ignores an older response for the same proposal after a newer preview is shown', () => {
    const current = proposal({ preview_version: 3 });
    expect(shouldReplaceActionProposal(current, proposal({ preview_version: 2 }))).toBe(false);
    expect(shouldReplaceActionProposal(current, proposal({ preview_version: 4 }))).toBe(true);
  });
});
