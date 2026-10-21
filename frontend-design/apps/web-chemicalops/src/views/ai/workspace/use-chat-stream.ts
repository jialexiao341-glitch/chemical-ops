import { onUnmounted, type Ref } from 'vue';
import { createFrameScheduler, createMessageRenderer } from './chat-rendering';

export function useChatStream(messagesRef: Ref<HTMLElement | undefined>, parse: (text: string) => string) {
  const scroll = createFrameScheduler(() => {
    const el = messagesRef.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
  onUnmounted(scroll.cancel);
  return { scrollToBottom: scroll.schedule, renderMessage: createMessageRenderer(parse) };
}
