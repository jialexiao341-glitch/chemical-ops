import { ref } from 'vue';

export function canSendFollowup(proposal: { action_type: string; status: string } | undefined, allowed: boolean) {
  return allowed && proposal?.action_type === 'deliveries.followup_draft' && proposal.status === 'EXECUTED';
}

/** 只由发送确认回调调用；保存草稿不触发发送。 */
export function useFollowupSend(api: (orderId: number, confirmationId: string, version: number) => Promise<unknown>) {
  const busy = ref(false);
  async function send(orderId: number, confirmationId: string, version: number) {
    if (busy.value) return false;
    busy.value = true;
    try {
      await api(orderId, confirmationId, version);
      return true;
    } finally { busy.value = false; }
  }
  return { busy, send };
}
