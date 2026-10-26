import { describe, expect, it, vi } from 'vitest';
import { canSendFollowup, useFollowupSend } from './followup-send';

describe('explicit followup sending', () => {
  it('only sends an executed saved draft with current permission', () => {
    expect(canSendFollowup({ action_type: 'deliveries.followup_draft', status: 'PENDING' }, true)).toBe(false);
    expect(canSendFollowup({ action_type: 'deliveries.followup_draft', status: 'EXECUTED' }, false)).toBe(false);
    expect(canSendFollowup({ action_type: 'other', status: 'EXECUTED' }, true)).toBe(false);
    expect(canSendFollowup({ action_type: 'deliveries.followup_draft', status: 'EXECUTED' }, true)).toBe(true);
  });
  it('does not send on initialization and serializes duplicate clicks', async () => {
    let finish!: () => void;
    const send = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const state = useFollowupSend(send);
    expect(send).not.toHaveBeenCalled();
    const first = state.send(1, 'proposal', 2);
    expect(await state.send(1, 'proposal', 2)).toBe(false);
    finish();
    expect(await first).toBe(true);
    expect(send).toHaveBeenCalledTimes(1);
  });
  it('releases loading after failure and does not silently retry', async () => {
    const send = vi.fn().mockRejectedValue(new Error('source changed'));
    const state = useFollowupSend(send);
    await expect(state.send(1, 'proposal', 1)).rejects.toThrow('source changed');
    expect(state.busy.value).toBe(false);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
