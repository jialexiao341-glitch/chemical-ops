<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';
import { Input, Modal, message } from 'antdv-next';
import { createReasonSubmission } from './submission';
const props = withDefaults(defineProps<{
  open: boolean;
  title: string;
  label?: string;
  okText?: string;
  placeholder?: string;
  submit: (reason: string) => Promise<unknown>;
}>(), { label: '原因', okText: '确认', placeholder: '请填写原因（必填）' });
const emit = defineEmits<{ 'update:open': [value: boolean]; success: [] }>();
const reason = ref('');
const loading = ref(false);
const input = ref<{ focus: () => void }>();
const submission = createReasonSubmission();
watch(() => props.open, async (open) => {
  if (open) { reason.value = ''; await nextTick(); input.value?.focus(); }
});
async function confirm() {
  if (loading.value) return;
  if (!reason.value.trim()) { message.warning(`请填写${props.label}`); input.value?.focus(); return; }
  loading.value = true;
  try {
    if (await submission.submit(reason.value, props.submit)) {
      emit('update:open', false);
      emit('success');
    }
  } catch { /* 请求层显示错误，保留原因以便重试。 */ }
  finally { loading.value = false; }
}
</script>
<template>
  <Modal :open="open" :title="title" :ok-text="okText" cancel-text="取消" :confirm-loading="loading" :closable="!loading" :mask-closable="!loading" :keyboard="!loading" :cancel-button-props="{ disabled: loading }" @ok="confirm" @cancel="!loading && emit('update:open', false)">
    <div class="py-2">
      <label class="mb-2 block text-sm" for="operation-reason">{{ label }} <span class="text-red-500">*</span></label>
      <Input.TextArea id="operation-reason" ref="input" v-model:value="reason" :maxlength="1000" :rows="3" :placeholder="placeholder" :disabled="loading" aria-required="true" />
    </div>
  </Modal>
</template>
