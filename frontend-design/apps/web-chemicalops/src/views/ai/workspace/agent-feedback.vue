<script setup lang="ts">
import type { AgentApi } from '#/api';
import { computed, onMounted, ref } from 'vue';
import { Button, Input, Select, message } from 'antdv-next';
import { getAgentFeedbackApi, submitAgentFeedbackApi } from '#/api/ai/agent';

const props = defineProps<{ task: AgentApi.Task }>();
const rating = ref<'DOWN' | 'UP'>();
const reason = ref<string>();
const comment = ref('');
const correction = ref('');
const saving = ref(false);
const formOpen = ref(false);
const terminal = computed(() => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(props.task.status));
const reasonOptions = [
  { value: 'FACT_ERROR', label: '事实或数值错误' },
  { value: 'SCOPE_ERROR', label: '范围或对象理解错' },
  { value: 'TOOL_ERROR', label: '工具选择或参数错' },
  { value: 'FORMAT', label: '格式或表述差' },
  { value: 'SLOW', label: '太慢' },
  { value: 'OTHER', label: '其他' },
];

onMounted(async () => {
  if (!terminal.value) return;
  const existing = await getAgentFeedbackApi(props.task.id);
  if (!existing) return;
  rating.value = existing.rating;
  reason.value = existing.reason_code ?? undefined;
  comment.value = existing.comment ?? '';
  correction.value = existing.correction ?? '';
  formOpen.value = existing.rating === 'DOWN';
});

async function submit(next: 'DOWN' | 'UP') {
  if (next === 'DOWN' && !reason.value) {
    message.warning('请选择没帮助的原因');
    return;
  }
  saving.value = true;
  try {
    const saved = await submitAgentFeedbackApi({
      task_id: props.task.id,
      rating: next,
      reason_code: next === 'DOWN' ? reason.value : undefined,
      comment: next === 'DOWN' ? comment.value || undefined : undefined,
      correction: next === 'DOWN' ? correction.value || undefined : undefined,
    });
    rating.value = saved.rating;
    if (next === 'UP') formOpen.value = false;
    message.success('反馈已记录，将用于后续评测');
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section v-if="terminal" class="agent-feedback">
    <div class="agent-feedback-actions">
      <span class="agent-muted">这次结果有帮助吗？</span>
      <Button size="small" :type="rating === 'UP' ? 'primary' : 'default'" :loading="saving" @click="submit('UP')">有帮助</Button>
      <Button size="small" :type="rating === 'DOWN' ? 'primary' : 'default'" @click="formOpen = true">没帮助</Button>
    </div>
    <div v-if="formOpen" class="agent-feedback-form">
      <Select v-model:value="reason" size="small" :options="reasonOptions" placeholder="选择原因" style="min-width: 180px" />
      <Input v-model:value="comment" size="small" placeholder="补充说明（可选）" />
      <Input.TextArea v-model:value="correction" :rows="2" placeholder="正确结果或期望（可选）" />
      <Button size="small" type="primary" :loading="saving" @click="submit('DOWN')">提交反馈</Button>
    </div>
  </section>
</template>

<style scoped>
.agent-feedback {
  margin-top: 0.75rem;
  border-top: 1px solid var(--border-color, rgb(0 0 0 / 8%));
  padding-top: 0.6rem;
}
.agent-feedback-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.agent-feedback-form {
  display: grid;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
</style>