import { computed, ref } from 'vue';

export function useConversation<T extends { id: number; title?: null | string; pinned?: boolean }>(load: () => Promise<{ items: T[] }>) {
  const conversations = ref<T[]>([]);
  const conversationsLoading = ref(false);
  const conversationSearch = ref('');
  const visibleConversations = computed(() => conversations.value.filter((item) =>
    (item.title || `会话 #${item.id}`).toLocaleLowerCase().includes(conversationSearch.value.trim().toLocaleLowerCase())));
  let revision = 0;
  async function loadConversations() {
    const current = ++revision;
    conversationsLoading.value = true;
    try { const res = await load(); if (current === revision) conversations.value = res.items as typeof conversations.value; }
    finally { if (current === revision) conversationsLoading.value = false; }
  }
  return { conversations, conversationsLoading, conversationSearch, visibleConversations, loadConversations };
}
