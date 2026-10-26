import type { AiApi } from '../../../api/ai';

import { ref } from 'vue';

interface FollowupApi {
  prepare: (orderId: number, idempotencyKey: string) => Promise<{ confirmation_id: string }>;
  get: (id: string) => Promise<AiApi.ActionProposalRead>;
  revise: (id: string, version: number, payload: Record<string, unknown>) => Promise<unknown>;
  confirm: (id: string, version: number) => Promise<unknown>;
  cancel: (id: string, version: number) => Promise<unknown>;
}

export function canPrepareFollowup(status: string | undefined, read: boolean, write: boolean, ai: boolean) {
  return Boolean(status && ['ORDERED', 'PARTIAL'].includes(status) && read && write && ai);
}

/** 失败即清空旧预览；所有动作串行，并重新读取服务端权限、状态与版本。 */
export function useFollowupProposal(api: FollowupApi) {
  const proposal = ref<AiApi.ActionProposalRead>();
  const busy = ref(false);
  const open = ref(false);
  const error = ref(false);
  let confirmationId: string | undefined;
  let targetOrderId: number | undefined;
  let requestKey = '';

  async function run(action: () => Promise<AiApi.ActionProposalRead>) {
    if (busy.value) return false;
    busy.value = true;
    error.value = false;
    proposal.value = undefined;
    try {
      proposal.value = await action();
      return true;
    } catch {
      error.value = true;
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function loadPrepared(orderId: number) {
    const preview = await api.prepare(orderId, requestKey);
    confirmationId = preview.confirmation_id;
    return api.get(confirmationId);
  }

  async function prepare(orderId: number) {
    if (busy.value) return false;
    confirmationId = undefined;
    targetOrderId = orderId;
    requestKey = globalThis.crypto?.randomUUID?.() ?? `followup-${Date.now()}-${Math.random()}`;
    open.value = true;
    return run(() => loadPrepared(orderId));
  }

  async function refresh() {
    if (!confirmationId) {
      const orderId = targetOrderId;
      return orderId ? run(() => loadPrepared(orderId)) : false;
    }
    const id = confirmationId;
    return run(() => api.get(id));
  }

  function editable() {
    const current = proposal.value;
    return current && !busy.value && current.requires_user_confirmation &&
      current.status === 'PENDING' && current.availability === 'AVAILABLE' && !current.blockers.length
      ? current : undefined;
  }

  async function revise(payload: Record<string, unknown>) {
    const current = editable();
    if (!current) return false;
    return run(async () => {
      await api.revise(current.confirmation_id, current.preview_version, payload);
      return api.get(current.confirmation_id);
    });
  }

  async function confirm() {
    const current = editable();
    if (!current) return false;
    return run(async () => {
      await api.confirm(current.confirmation_id, current.preview_version);
      return api.get(current.confirmation_id);
    });
  }

  async function cancel() {
    const current = editable();
    if (!current) return false;
    return run(async () => {
      await api.cancel(current.confirmation_id, current.preview_version);
      return api.get(current.confirmation_id);
    });
  }

  return { proposal, busy, open, error, prepare, refresh, revise, confirm, cancel };
}
