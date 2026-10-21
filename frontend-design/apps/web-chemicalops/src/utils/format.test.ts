import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatAmount, formatDate, formatDateTime, formatQuantity } from './format';
afterEach(() => vi.unstubAllEnvs());
describe('数值展示格式', () => {
 it('数量去掉 Decimal 末尾零，保留精确的小数文本', () => {
  expect(formatQuantity('126.000000')).toBe('126');
  expect(formatQuantity('99.500000')).toBe('99.5');
  expect(formatQuantity('9007199254740993.123456')).toBe('9,007,199,254,740,993.123456');
 });
 it('限制计算结果的展示精度，避免浮点尾数', () => {
  expect(formatQuantity(0.1 + 0.2)).toBe('0.3');
  expect(formatQuantity('1.005', 2)).toBe('1.01');
  expect(formatQuantity('-0.0000001', 6)).toBe('0');
 });
 it('金额默认两位小数并省略不必要的尾零', () => {
  expect(formatAmount('120.000000')).toBe('120');
  expect(formatAmount('1.235')).toBe('1.24');
 });
});
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
