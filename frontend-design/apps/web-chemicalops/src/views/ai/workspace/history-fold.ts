const HISTORY_WINDOW_MS = 30 * 24 * 60 * 60 * 1000;

/** 仅折叠连续的旧消息，始终保留末尾一轮及缺少时间的本地消息。 */
export function historyFoldStart(items: Array<{ createdAt?: string }>, now = Date.now()): number {
  const maximum = Math.max(0, items.length - 2);
  let start = 0;
  while (start < maximum) {
    const time = items[start]?.createdAt ? Date.parse(items[start]!.createdAt!) : Number.NaN;
    if (!Number.isFinite(time) || time >= now - HISTORY_WINDOW_MS) break;
    start += 1;
  }
  return start;
}
