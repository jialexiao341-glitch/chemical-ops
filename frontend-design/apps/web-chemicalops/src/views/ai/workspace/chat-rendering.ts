export function createMessageRenderer(parse: (text: string) => string) {
  const cache = new Map<string, { text: string; html: string }>();
  return (id: string, text: string) => {
    const previous = cache.get(id);
    if (previous?.text === text) return previous.html;
    const html = parse(text);
    cache.set(id, { text, html });
    // 会话切换后不无限保留已离开的消息。
    if (cache.size > 300) cache.delete(cache.keys().next().value!);
    return html;
  };
}
export function createFrameScheduler(
  action: () => void,
  request: (callback: FrameRequestCallback) => number = requestAnimationFrame,
  cancel: (id: number) => void = cancelAnimationFrame,
) {
  let frame: number | undefined;
  return {
    schedule() {
      if (frame !== undefined) return;
      frame = request(() => { frame = undefined; action(); });
    },
    cancel() { if (frame !== undefined) cancel(frame); frame = undefined; },
  };
}
