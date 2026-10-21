import { describe, expect, it } from 'vitest';
import * as confirmation from './submission';

describe('原因确认提交', () => {
  it('空白原因不执行，重复确认仅执行一次，失败恢复后可重试', async () => {
    expect(confirmation.createReasonSubmission).toBeTypeOf('function');
    let calls = 0;
    let finish!: () => void;
    const state = confirmation.createReasonSubmission();
    expect(await state.submit('  ', async () => { calls++; })).toBe(false);
    const first = state.submit(' 原因 ', async (reason) => { expect(reason).toBe('原因'); calls++; await new Promise<void>((resolve) => { finish = resolve; }); });
    expect(await state.submit('原因', async () => { calls++; })).toBe(false);
    expect(calls).toBe(1);
    finish();
    expect(await first).toBe(true);
    await expect(state.submit('原因', async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    expect(await state.submit('重试', async () => { calls++; })).toBe(true);
    expect(calls).toBe(2);
  });
});
