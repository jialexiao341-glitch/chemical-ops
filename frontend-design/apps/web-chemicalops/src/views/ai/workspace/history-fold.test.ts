import { describe, expect, it } from 'vitest';
import { historyFoldStart } from './history-fold';

describe('历史消息默认收起', () => {
  const now = Date.parse('2026-10-27T12:00:00Z');
  it('收起 30 天前的消息，保留新消息', () => {
    const items = [{ createdAt: '2026-09-01T00:00:00Z' }, { createdAt: '2026-10-26T00:00:00Z' }, { createdAt: '2026-10-27T00:00:00Z' }];
    expect(historyFoldStart(items, now)).toBe(1);
  });
  it('全是旧消息时保留最后一轮，缺少时间的新消息保持可见', () => {
    expect(historyFoldStart(Array.from({ length: 5 }, () => ({ createdAt: '2026-01-01T00:00:00Z' })), now)).toBe(3);
    expect(historyFoldStart([{ createdAt: '2026-01-01T00:00:00Z' }, { createdAt: undefined }], now)).toBe(0);
    expect(historyFoldStart([], now)).toBe(0);
  });
});
