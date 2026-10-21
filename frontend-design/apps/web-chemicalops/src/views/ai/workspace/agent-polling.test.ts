import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAgentPoller } from './agent-polling';

describe('Agent polling', () => {
  afterEach(() => vi.useRealTimers());
  it('后台不查询，恢复后按退避刷新，终态停止', async () => {
    vi.useFakeTimers();
    let hidden = true;
    let pending = true;
    const refresh = vi.fn(async () => {});
    const poller = createAgentPoller({ hidden: () => hidden, pending: () => pending, refresh, timeout: vi.fn() });
    poller.schedule();
    await vi.advanceTimersByTimeAsync(5000);
    expect(refresh).not.toHaveBeenCalled();
    hidden = false;
    poller.schedule();
    await vi.advanceTimersByTimeAsync(2000);
    expect(refresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2999);
    expect(refresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(refresh).toHaveBeenCalledTimes(2);
    pending = false;
    poller.schedule();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('十分钟暂停，重置可重新启动', async () => {
    vi.useFakeTimers();
    const timeout = vi.fn();
    const refresh = vi.fn(async () => {});
    const poller = createAgentPoller({ hidden: () => false, pending: () => true, refresh, timeout });
    poller.schedule();
    await vi.advanceTimersByTimeAsync(620_000);
    expect(timeout).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    poller.reset(); poller.schedule();
    expect(vi.getTimerCount()).toBe(1);
    poller.stop();
  });
  it('切换会话期间的迟到读取不再重启计时器', async () => {
    vi.useFakeTimers();
    let finish!: () => void;
    const poller = createAgentPoller({ hidden: () => false, pending: () => true,
      refresh: () => new Promise<void>((resolve) => { finish = resolve; }), timeout: vi.fn() });
    poller.schedule();
    await vi.advanceTimersByTimeAsync(2000);
    poller.reset(); finish();
    await Promise.resolve();
    expect(vi.getTimerCount()).toBe(0);
  });
});
