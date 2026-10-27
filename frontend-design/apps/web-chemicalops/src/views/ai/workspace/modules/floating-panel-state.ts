/** 仅缓存当前页面会话已完成的回答；账号切换时由调用方清空。 */
export class PanelAnswerCache<T> {
  private entries = new Map<string, { turns: T[]; conversationId: null | number }>();
  clear() { this.entries.clear(); }
  delete(key: string) { this.entries.delete(key); }
  get(key: string) { return this.entries.get(key); }
  save(key: string, turns: T[], conversationId: null | number) {
    if (turns.length) this.entries.set(key, { turns: JSON.parse(JSON.stringify(turns)), conversationId });
  }
}

export function shouldDismissAssistant(open: boolean, target: { closest: (selector: string) => unknown } | null) {
  if (!open || !target) return false;
  return !target.closest('.page-copilot-panel, .chemical-agent, .ant-select-dropdown, .ant-dropdown, [data-radix-popper-content-wrapper]');
}

export function sameAuthorizedEvidence(
  previous: Array<{ context: unknown; citations: unknown }>,
  current: { context: unknown; citations: unknown },
) {
  const expected = JSON.stringify({ context: current.context, citations: current.citations });
  return previous.every((entry) => JSON.stringify({ context: entry.context, citations: entry.citations }) === expected);
}

/** 打开面板只决定展示状态，业务历史必须由用户主动触发核验。 */
export function openingAction(isGeneral: boolean, hasSaved: boolean): 'idle' | 'confirm_restore' | 'restore_local' {
  if (!hasSaved) return 'idle';
  return isGeneral ? 'restore_local' : 'confirm_restore';
}
