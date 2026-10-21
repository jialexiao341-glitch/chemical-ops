import { describe, expect, it, vi } from 'vitest';
import { createSseParser } from './sse-parser';

describe('SSE frames', () => {
  it('支持每个字符分块的 CRLF、多事件和无空行末帧', () => {
    const event = vi.fn();
    const parse = createSseParser(event);
    for (const char of 'event: delta\r\ndata: {"content":"甲"}\r\n\r\nevent: done\r\ndata: {"answer":"甲"}') parse(char);
    parse('', true);
    expect(event.mock.calls).toEqual([['delta', '{"content":"甲"}'], ['done', '{"answer":"甲"}']]);
  });
  it('忽略心跳、多行 data 拼接、事件名不跨帧继承', () => {
    const event = vi.fn();
    const parse = createSseParser(event);
    parse(': heartbeat\n\nevent: delta\ndata: {\ndata: "content":"x"}\n\ndata: {}\n\n');
    expect(event.mock.calls).toEqual([['delta', '{\n"content":"x"}'], ['message', '{}']]);
  });
});
