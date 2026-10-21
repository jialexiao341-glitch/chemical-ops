import { describe, expect, it } from 'vitest';
import * as rendering from './chat-rendering';
describe('聊天渲染调度', () => {
 it('同内容只解析一次且只保留每条消息的最新内容', () => {
  expect(rendering.createMessageRenderer).toBeTypeOf('function');
  let parses=0;
  const render=rendering.createMessageRenderer((text) => {parses++; return text.toUpperCase();});
  expect(render('a','hello')).toBe('HELLO'); expect(render('a','hello')).toBe('HELLO');
  render('b','other'); render('a','next'); expect(parses).toBe(3);
 });
 it('同帧多次更新只滚动一次，取消后不回调', () => {
  expect(rendering.createFrameScheduler).toBeTypeOf('function');
  const queued = new Map<number, FrameRequestCallback>(); let seq=0; let calls=0;
  const scheduler=rendering.createFrameScheduler(() => { calls++; }, cb => { queued.set(++seq,cb); return seq; }, id => queued.delete(id));
  scheduler.schedule(); scheduler.schedule(); expect(queued.size).toBe(1);
  for (const cb of queued.values()) cb(0); queued.clear(); expect(calls).toBe(1);
  scheduler.schedule(); scheduler.cancel(); expect(queued.size).toBe(0);
 });
});
