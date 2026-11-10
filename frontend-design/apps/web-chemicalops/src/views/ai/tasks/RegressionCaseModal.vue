<script lang="ts" setup>
import type { AgentApi } from '#/api';

import { computed, ref, watch } from 'vue';
import { Checkbox, Input, Modal, Select, message } from 'antdv-next';

import {
  createRegressionCaseApi,
  getRegressionCaseDraftApi,
  getRegressionCaseOptionsApi,
} from '#/api';

const props = defineProps<{ open: boolean; task?: AgentApi.Task }>();
const emit = defineEmits<{ created: [AgentApi.RegressionCase]; 'update:open': [boolean] }>();

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
});
const loading = ref(false);
const submitting = ref(false);
const options = ref<AgentApi.RegressionCaseOptions>();
const question = ref('');
const mode = ref('agent');
const expected = ref<string[]>([]);
const forbidden = ref<string[]>([]);
const note = ref('');
const redacted = ref(false);
const modeLabels: Record<string, string> = {
  agent: 'Agent 只读任务',
  batch: '多意图批次',
  document: '文档问答',
  none: '不执行',
  query: '统计查询',
};
const modeOptions = computed(() => (options.value?.modes ?? ['agent', 'batch', 'query', 'document', 'none'])
  .map((value) => ({ label: modeLabels[value] ?? value, value })));
const expectedOptions = computed(() => (options.value?.tasks ?? [])
  .filter((item) => !forbidden.value.includes(item.key)));
const forbiddenOptions = computed(() => (options.value?.tasks ?? [])
  .filter((item) => !expected.value.includes(item.key)));
const canSubmit = computed(() => question.value.trim().length >= 5 && redacted.value && !submitting.value);

async function loadDraft() {
  if (!props.task) return;
  loading.value = true;
  try {
    const [optionResult, draft] = await Promise.all([
      getRegressionCaseOptionsApi(),
      getRegressionCaseDraftApi(props.task.id),
    ]);
    options.value = optionResult;
    question.value = draft.question;
    mode.value = draft.expected_execution_mode;
    expected.value = draft.expected_tasks;
    forbidden.value = draft.forbidden_tasks;
  } catch {
    message.error('回归用例草稿读取失败，请确认任务归属与权限');
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.open, props.task?.id],
  ([open]) => {
    if (!open) return;
    redacted.value = false;
    note.value = '';
    if (props.task) void loadDraft();
    else question.value = '';
  },
  { immediate: true },
);

async function submit() {
  if (!canSubmit.value) return;
  submitting.value = true;
  try {
    const created = await createRegressionCaseApi({
      expected_execution_mode: mode.value,
      expected_tasks: expected.value,
      forbidden_tasks: forbidden.value,
      note: note.value.trim() || null,
      question: question.value.trim(),
      redacted_confirmed: redacted.value,
      source_task_id: props.task?.id ?? null,
    });
    message.success(`已提交回归用例 ${created.case_key}，等待管理员审阅`);
    emit('created', created);
    visible.value = false;
  } catch (error: any) {
    message.error(error?.message || '回归用例提交失败');
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Modal
    v-model:open="visible"
    :confirm-loading="submitting"
    :ok-button-props="{ disabled: !canSubmit }"
    :width="720"
    cancel-text="取消"
    ok-text="提交审阅"
    title="转为回归用例"
    @ok="submit"
  >
    <div v-if="loading" role="status" class="py-6 text-center text-muted-foreground">正在读取任务与可选任务类别…</div>
    <div v-else class="space-y-4">
      <div class="rounded border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        回归用例会进入评测集。提交前请手动删除客户名称、联系人、联系方式、真实单号等敏感信息；系统不会自动脱敏。
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium" for="regression-question">脱敏后的问题</label>
        <Input.TextArea
          id="regression-question"
          v-model:value="question"
          :maxlength="2000"
          :rows="4"
          placeholder="复制任务问题后手动脱敏，至少 5 个字符"
          show-count
        />
      </div>
      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-sm font-medium" for="regression-mode">期望执行模式</label>
          <Select id="regression-mode" v-model:value="mode" :options="modeOptions" class="w-full" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium" for="regression-expected">必须包含的任务</label>
          <Select
            id="regression-expected"
            v-model:value="expected"
            :options="expectedOptions"
            class="w-full"
            mode="multiple"
            placeholder="可留空，由评测契约按原任务轨迹推导"
          />
        </div>
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium" for="regression-forbidden">禁止出现的任务</label>
        <Select
          id="regression-forbidden"
          v-model:value="forbidden"
          :options="forbiddenOptions"
          class="w-full"
          mode="multiple"
          placeholder="选填"
        />
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium" for="regression-note">说明（选填）</label>
        <Input id="regression-note" v-model:value="note" :maxlength="500" placeholder="记录差评原因、期望行为或复现条件" />
      </div>
      <Checkbox v-model:checked="redacted">
        我已手动脱敏，确认问题文本不含客户、联系人、联系方式、真实单号等敏感信息
      </Checkbox>
    </div>
  </Modal>
</template>
