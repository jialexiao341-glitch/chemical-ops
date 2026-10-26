import { describe, expect, it, vi } from 'vitest';

import { canPrepareFollowup, useFollowupProposal } from './followup-proposal';

function fixture() {
  let current = {
    confirmation_id: 'a'.repeat(32), preview_version: 1, status: 'PENDING',
    requires_user_confirmation: true, blockers: [], action_type: 'deliveries.followup_draft',
    revision_values: { followup_note: '' }, availability: 'AVAILABLE',
  };
  const api = {
    prepare: vi.fn(async () => current),
    get: vi.fn(async () => current),
    revise: vi.fn(async (_id, _version, payload) => {
      current = { ...current, preview_version: 2, revision_values: payload };
    }),
    confirm: vi.fn(async () => {
      current = { ...current, status: 'EXECUTED', requires_user_confirmation: false };
    }),
    cancel: vi.fn(async () => {
      current = { ...current, status: 'CANCELLED', requires_user_confirmation: false };
    }),
  };
  return { api, state: useFollowupProposal(api as any) };
}

describe('order followup proposal lifecycle', () => {
  it('resumes the saved draft from Inbox without creating or confirming another proposal', async () => {
    const { api, state } = fixture();
    api.get.mockResolvedValueOnce({ ...(await api.get()), resource_id: '41', status: 'EXECUTED' } as any);
    expect(await state.resume(41, 'a'.repeat(32))).toBe(true);
    expect(state.proposal.value?.status).toBe('EXECUTED');
    expect(api.prepare).not.toHaveBeenCalled();
    expect(api.confirm).not.toHaveBeenCalled();
    api.get.mockResolvedValueOnce({ ...(await api.get()), resource_id: '42' } as any);
    expect(await state.resume(41, 'foreign')).toBe(false);
    expect(state.proposal.value).toBeUndefined();
  });
  it('only opens for active fulfilment orders with both order permissions and AI access', () => {
    expect(canPrepareFollowup('ORDERED', true, true, true)).toBe(true);
    expect(canPrepareFollowup('PARTIAL', true, true, true)).toBe(true);
    for (const status of ['DRAFT', 'APPROVING', 'APPROVED', 'COMPLETED', 'CANCELLED']) {
      expect(canPrepareFollowup(status, true, true, true)).toBe(false);
    }
    expect(canPrepareFollowup('ORDERED', false, true, true)).toBe(false);
    expect(canPrepareFollowup('ORDERED', true, false, true)).toBe(false);
    expect(canPrepareFollowup('ORDERED', true, true, false)).toBe(false);
  });

  it('reads authoritative detail after prepare and every revision; confirms the displayed version once', async () => {
    const { api, state } = fixture();
    await state.prepare(41);
    expect(api.prepare).toHaveBeenCalledWith(41, expect.any(String));
    expect(api.confirm).not.toHaveBeenCalled();
    await state.revise({ followup_note: '请反馈交期' });
    expect(state.proposal.value?.preview_version).toBe(2);
    await state.confirm();
    expect(api.confirm).toHaveBeenCalledWith('a'.repeat(32), 2);
    expect(state.proposal.value?.status).toBe('EXECUTED');
    await state.confirm();
    expect(api.confirm).toHaveBeenCalledTimes(1);
  });

  it('clears stale preview after a rejected confirmation, allows refresh and prevents reuse', async () => {
    const { api, state } = fixture();
    await state.prepare(41);
    api.confirm.mockRejectedValueOnce(new Error('资源变化'));
    await state.confirm();
    expect(state.proposal.value).toBeUndefined();
    expect(state.error.value).toBe(true);
    await state.confirm();
    expect(api.confirm).toHaveBeenCalledTimes(1);
    await state.refresh();
    expect(state.error.value).toBe(false);
    expect(state.proposal.value?.preview_version).toBe(1);
  });

  it('serializes prepare requests and cancellation never confirms', async () => {
    const { api, state } = fixture();
    const preparing = state.prepare(41);
    await state.prepare(42);
    await preparing;
    expect(api.prepare).toHaveBeenCalledTimes(1);
    await state.cancel();
    expect(state.proposal.value?.status).toBe('CANCELLED');
    expect(api.confirm).not.toHaveBeenCalled();
  });

  it('can retry preparation when the first request fails before an identifier is returned', async () => {
    const { api, state } = fixture();
    api.prepare.mockRejectedValueOnce(new Error('网络暂不可用'));
    await state.prepare(41);
    expect(state.error.value).toBe(true);
    await state.refresh();
    expect(api.prepare).toHaveBeenCalledTimes(2);
    expect(api.prepare.mock.calls[0]).toEqual(api.prepare.mock.calls[1]);
    expect(state.proposal.value?.confirmation_id).toBe('a'.repeat(32));
    expect(state.error.value).toBe(false);
  });
});
