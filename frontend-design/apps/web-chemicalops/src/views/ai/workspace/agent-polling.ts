/** 每轮仅一个计时器；后台暂停，读取退避，十分钟后交由用户核对。 */
export function createAgentPoller(options: {
  hidden: () => boolean;
  pending: () => boolean;
  refresh: () => Promise<void>;
  timeout: () => void;
}) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let startedAt: number | undefined;
  let delay = 2000;
  let generation = 0;
  function stop() { if (timer) clearTimeout(timer); timer = undefined; generation += 1; }
  function reset() { stop(); startedAt = undefined; delay = 2000; }
  function schedule() {
    stop();
    if (!options.pending()) { startedAt = undefined; delay = 2000; return; }
    startedAt ??= Date.now();
    if (options.hidden()) return;
    if (Date.now() - startedAt >= 10 * 60_000) { options.timeout(); return; }
    const current = generation;
    timer = setTimeout(async () => {
      timer = undefined;
      try { await options.refresh(); }
      finally {
        if (current === generation) { delay = Math.min(delay * 1.5, 10_000); schedule(); }
      }
    }, delay);
  }
  return { reset, schedule, stop };
}
