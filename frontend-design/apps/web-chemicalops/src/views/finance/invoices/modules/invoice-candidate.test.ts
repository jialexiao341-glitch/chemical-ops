import { describe, expect, it } from 'vitest';
import { candidateAmount } from './invoice-candidate';

describe('发票候选金额', () => {
  it('保留六位内的可展示金额，缺失值不推断为零', () => {
    expect(candidateAmount('100.250000')).toEqual({ value: 100.25, valid: true });
    expect(candidateAmount('0')).toEqual({ value: 0, valid: true });
    expect(candidateAmount(null)).toEqual({ value: null, valid: true });
  });
  it('拒绝会因数字控件丢失精度的金额', () => {
    expect(candidateAmount('999999999999.123456')).toEqual({ value: null, valid: false });
    expect(candidateAmount('1e2')).toEqual({ value: null, valid: false });
  });
});
