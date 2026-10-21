import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatDate, formatDateTime } from './format';
afterEach(() => vi.unstubAllEnvs());
describe('业务时区展示', () => {
 it('显式UTC和offset转换上海时间且不依赖浏览器时区', () => {
  vi.stubEnv('TZ', 'UTC');
  expect(formatDateTime('2026-10-20T18:30:00Z')).toBe('2026-10-21 02:30');
  expect(formatDate('2026-10-20T18:30:00Z')).toBe('2026-10-21');
  expect(formatDateTime('2026-10-20T18:30:00-04:00')).toBe('2026-10-21 06:30');
 });
 it('无时区历史时间和业务日期保留墙上值', () => {
  expect(formatDateTime('2026-10-20T18:30:00')).toBe('2026-10-20 18:30');
  expect(formatDateTime('2026-10-20')).toBe('2026-10-20');
  expect(formatDate('2026-10-20')).toBe('2026-10-20');
 });
});
