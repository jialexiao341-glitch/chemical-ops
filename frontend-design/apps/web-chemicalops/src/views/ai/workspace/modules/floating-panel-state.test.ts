import { describe, expect, it } from 'vitest';
import { PanelAnswerCache, openingAction, sameAuthorizedEvidence, shouldDismissAssistant } from './floating-panel-state';

describe('悬浮助手交互状态', () => {
  it('打开面板不自动发起查询：有业务历史时等待用户主动恢复', () => {
    expect(openingAction(false, false)).toBe('idle');
    expect(openingAction(false, true)).toBe('confirm_restore');
    expect(openingAction(true, true)).toBe('restore_local');
  });
  it('只在打开时点击面板和下拉框以外的位置收起', () => {
    expect(shouldDismissAssistant(true, { closest: () => null })).toBe(true);
    expect(shouldDismissAssistant(true, { closest: () => ({}) })).toBe(false);
    expect(shouldDismissAssistant(false, { closest: () => null })).toBe(false);
  });
  it('权限或业务来源变化时不恢复历史内容', () => {
    const before = { context: { source_records: [{ record_id: 1 }] }, citations: [{ status: 'AVAILABLE' }] };
    expect(sameAuthorizedEvidence([before], before)).toBe(true);
    expect(sameAuthorizedEvidence([before], { ...before, citations: [{ status: 'NO_PERMISSION' }] })).toBe(false);
    expect(sameAuthorizedEvidence([before], { ...before, context: { source_records: [] } })).toBe(false);
  });
  it('按范围恢复完成的回答并隔离后续变更', () => {
    const cache = new PanelAnswerCache<{ answer: string }>();
    const turns = [{ answer: '已有回答' }];
    cache.save('purchase_order:1', turns, null);
    turns[0]!.answer = '新内容';
    expect(cache.get('purchase_order:1')?.turns[0]?.answer).toBe('已有回答');
    expect(cache.get('purchase_order:2')).toBeUndefined();
    cache.clear();
    expect(cache.get('purchase_order:1')).toBeUndefined();
  });
});
