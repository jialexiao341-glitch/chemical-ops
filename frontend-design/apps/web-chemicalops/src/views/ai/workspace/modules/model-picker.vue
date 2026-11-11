<script lang="ts" setup>
import type { AIModelProfileApi } from '#/api';

import { computed, onMounted, reactive, ref } from 'vue';

import { useAccess } from '@vben/access';

import { Button, Input, InputNumber, message, Modal, Popover, Select } from 'antdv-next';

import {
  activateModelProfileApi,
  createModelProfileApi,
  deleteModelProfileApi,
  getModelProfilesApi,
  probeModelProfileApi,
  updateModelProfileApi,
} from '#/api';

defineOptions({ name: 'AiModelPicker' });

const emit = defineEmits<{ changed: [profile: AIModelProfileApi.ModelProfile] }>();
const { hasAccessByCodes } = useAccess();
const canRead = computed(() => hasAccessByCodes(['ai.workspace.read']));
const canWrite = computed(() => hasAccessByCodes(['ai.models.write']));

const profiles = ref<AIModelProfileApi.ModelProfile[]>([]);
const open = ref(false);
const switchingId = ref<number>();
const current = computed(() => profiles.value.find((item) => item.is_default));

type EffortValue = '' | 'high' | 'low' | 'medium';
const EFFORT_OPTIONS: Array<{ label: string; value: EffortValue }> = [
  { label: '默认', value: '' },
  { label: '低', value: 'low' },
  { label: '中', value: 'medium' },
  { label: '高', value: 'high' },
];
const effortSaving = ref(false);

function effortLabel(value: null | string | undefined) {
  return EFFORT_OPTIONS.find((option) => option.value === (value ?? ''))?.label ?? '默认';
}

const configOpen = ref(false);
const editingId = ref<null | number>(null);
const saving = ref(false);
const form = reactive({
  name: '',
  model: '',
  base_url: '',
  api_key: '',
  context_window: null as null | number,
  max_tokens: null as null | number,
  reasoning_effort: '' as EffortValue,
});
const editingIsCurrent = computed(
  () => profiles.value.find((item) => item.id === editingId.value)?.is_default === true,
);

async function loadProfiles() {
  if (!canRead.value) return;
  try {
    const result = await getModelProfilesApi();
    profiles.value = result.items;
  } catch {
    // 请求层已提示；保留上一次可用列表
  }
}

onMounted(loadProfiles);

async function selectProfile(profile: AIModelProfileApi.ModelProfile) {
  if (profile.is_default || switchingId.value) {
    open.value = false;
    return;
  }
  switchingId.value = profile.id;
  try {
    const activated = await activateModelProfileApi(profile.id);
    await loadProfiles();
    message.success(`已切换到 ${activated.name} · ${activated.model}（连通性正常）`);
    open.value = false;
    emit('changed', activated);
  } catch {
    // 后端返回连通性失败原因，由请求层统一提示；切换不生效
  } finally {
    switchingId.value = undefined;
  }
}

async function setEffort(value: EffortValue) {
  const profile = current.value;
  if (!profile || !canWrite.value || effortSaving.value) return;
  if ((profile.reasoning_effort ?? '') === value) return;
  effortSaving.value = true;
  try {
    await updateModelProfileApi(profile.id, {
      reasoning_effort: value || null,
    });
    await loadProfiles();
    message.success(`思考强度已设为${effortLabel(value)}`);
  } catch {
    // 请求层已提示
  } finally {
    effortSaving.value = false;
  }
}

function resetForm() {
  form.name = '';
  form.model = '';
  form.base_url = '';
  form.api_key = '';
  form.context_window = null;
  form.max_tokens = null;
  form.reasoning_effort = '';
}

function addProfile() {
  if (!canWrite.value) return;
  editingId.value = null;
  resetForm();
}

function editProfile(profile: AIModelProfileApi.ModelProfile) {
  editingId.value = profile.id;
  form.name = profile.name;
  form.model = profile.model;
  form.base_url = profile.base_url;
  form.api_key = '';
  form.context_window = profile.context_window;
  form.max_tokens = profile.max_tokens;
  form.reasoning_effort = profile.reasoning_effort ?? '';
}

function openConfig() {
  open.value = false;
  if (!canWrite.value) return;
  configOpen.value = true;
  const target = current.value ?? profiles.value[0];
  if (target) editProfile(target);
  else addProfile();
}

async function saveProfile(testAfterSave = false) {
  if (!canWrite.value) return;
  const name = form.name.trim();
  const model = form.model.trim();
  const baseUrl = form.base_url.trim();
  if (!name || !model || !baseUrl) {
    message.warning('请填写显示名称、API 地址和模型标识');
    return;
  }
  const payload: AIModelProfileApi.ProfilePayload = {
    name,
    model,
    base_url: baseUrl,
    context_window: form.context_window ?? null,
    max_tokens: form.max_tokens ?? null,
    reasoning_effort: form.reasoning_effort || null,
  };
  if (form.api_key.trim()) payload.api_key = form.api_key.trim();
  saving.value = true;
  try {
    const saved = editingId.value
      ? await updateModelProfileApi(editingId.value, payload)
      : await createModelProfileApi(payload);
    editingId.value = saved.id;
    form.api_key = '';
    await loadProfiles();
    message.success('模型配置已保存');
    if (testAfterSave) await probeProfile(saved.id);
  } catch {
    // 请求层已提示
  } finally {
    saving.value = false;
  }
}

async function probeProfile(id: number) {
  try {
    const result = await probeModelProfileApi(id);
    if (result.ok) message.success(`连通性正常 · ${result.latency_ms} ms`);
    else message.error(`连通性检查失败：${result.message}`);
  } catch {
    // 请求层已提示
  }
}

function removeProfile() {
  const target = profiles.value.find((item) => item.id === editingId.value);
  if (!target || target.is_default) return;
  Modal.confirm({
    title: '删除模型配置',
    content: `删除后无法恢复：${target.name} · ${target.model}`,
    okText: '删除',
    okButtonProps: { danger: true },
    onOk: async () => {
      await deleteModelProfileApi(target.id);
      await loadProfiles();
      message.success('模型配置已删除');
      const next = current.value ?? profiles.value[0];
      if (next) editProfile(next);
      else addProfile();
    },
  });
}
</script>

<template>
  <div v-if="canRead" class="ai-model-picker">
    <Popover
      v-model:open="open"
      :trigger="['click']"
      placement="topRight"
      :arrow="false"
      :styles="{ container: { padding: '0', borderRadius: '14px' } }"
    >
      <button
        type="button"
        class="ai-model-trigger"
        :aria-expanded="open"
        :title="current ? `${current.name} · ${current.model} · 思考强度${effortLabel(current.reasoning_effort)}` : '选择模型'"
      >
        <span class="ai-model-trigger-name">{{ current?.model ?? '选择模型' }}</span>
        <span v-if="current?.reasoning_effort" class="ai-model-trigger-effort">{{ effortLabel(current.reasoning_effort) }}</span>
        <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path d="m5 8 5 5 5-5" />
        </svg>
      </button>
      <template #content>
        <section class="ai-model-menu" aria-label="选择模型">
          <div class="ai-model-menu-head">
            <span>选择模型</span>
            <span class="ai-model-menu-current">{{ current?.name ?? '未配置' }}</span>
          </div>
          <button
            v-for="profile in profiles"
            :key="profile.id"
            type="button"
            class="ai-model-option"
            :class="{ 'is-current': profile.is_default }"
            :disabled="Boolean(switchingId)"
            @click="selectProfile(profile)"
          >
            <span class="ai-model-option-main">
              <span class="ai-model-option-provider">{{ profile.name }}</span>
              <span class="ai-model-option-model">{{ profile.model }}<small v-if="profile.reasoning_effort" class="ai-model-option-effort"> · {{ effortLabel(profile.reasoning_effort) }}</small></span>
            </span>
            <span v-if="switchingId === profile.id" class="ai-model-option-state">检查连通性…</span>
            <svg v-else-if="profile.is_default" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <path d="m4 10 4 4 8-8" />
            </svg>
          </button>
          <p v-if="!profiles.length" class="ai-model-menu-empty">尚未配置模型，请先在模型配置中新增。</p>
          <div v-if="current || canWrite" class="ai-model-menu-foot">
            <div class="ai-model-effort">
              <span>思考强度</span>
              <div class="ai-model-effort-options">
                <button
                  v-for="option in EFFORT_OPTIONS"
                  :key="option.label"
                  type="button"
                  :class="{ 'is-active': (current?.reasoning_effort ?? '') === option.value }"
                  :disabled="!canWrite || !current || effortSaving"
                  @click="setEffort(option.value)"
                >
                  {{ option.label }}
                </button>
              </div>
            </div>
            <button v-if="canWrite" class="ai-model-config-link" type="button" @click="openConfig">模型配置</button>
          </div>
        </section>
      </template>
    </Popover>

    <Modal v-model:open="configOpen" title="模型配置" :footer="null" width="720px">
      <div class="ai-model-config">
        <div class="ai-model-config-list">
          <button
            v-for="profile in profiles"
            :key="profile.id"
            type="button"
            class="ai-model-config-row"
            :class="{ 'is-active': editingId === profile.id }"
            @click="editProfile(profile)"
          >
            <span class="ai-model-config-row-main">
              <strong>{{ profile.name }}</strong>
              <small>{{ profile.model }}</small>
            </span>
            <span v-if="profile.is_default" class="ai-model-badge">当前使用</span>
          </button>
          <button type="button" class="ai-model-config-add" @click="addProfile">+ 新增模型</button>
        </div>
        <div class="ai-model-config-form">
          <label class="ai-model-field">
            <span>显示名称</span>
            <Input v-model:value="form.name" :maxlength="64" placeholder="例如：MaxApi" />
          </label>
          <label class="ai-model-field">
            <span>API 协议</span>
            <Input value="OpenAI Chat Completions" disabled />
          </label>
          <label class="ai-model-field">
            <span>API 地址</span>
            <Input v-model:value="form.base_url" :maxlength="255" placeholder="https://ai.max66.xyz/v1" />
          </label>
          <label class="ai-model-field">
            <span>模型标识</span>
            <Input v-model:value="form.model" :maxlength="128" placeholder="deepseek-v4.1-flash" />
          </label>
          <label class="ai-model-field">
            <span>API 密钥</span>
            <Input.Password
              v-model:value="form.api_key"
              :maxlength="512"
              autocomplete="new-password"
              :placeholder="editingId ? '留空使用已保存凭据' : 'sk-...'"
            />
          </label>
          <div class="ai-model-field-grid">
            <label class="ai-model-field">
              <span>上下文窗口</span>
              <InputNumber v-model:value="form.context_window" class="w-full" :min="1" :precision="0" />
            </label>
            <label class="ai-model-field">
              <span>最大输出 token</span>
              <InputNumber v-model:value="form.max_tokens" class="w-full" :min="1" :precision="0" />
            </label>
          </div>
          <label class="ai-model-field">
            <span>思考强度</span>
            <Select v-model:value="form.reasoning_effort" :options="EFFORT_OPTIONS" />
          </label>
          <p class="ai-model-hint">切换模型前会先向目标模型发送一次探测请求；探测失败时不会切换。</p>
          <div class="ai-model-config-actions">
            <Button v-if="editingId" danger :disabled="editingIsCurrent" @click="removeProfile">删除</Button>
            <span class="ai-model-actions-spacer"></span>
            <Button v-if="editingId" :loading="saving" @click="saveProfile(true)">保存并测试</Button>
            <Button type="primary" :loading="saving" @click="saveProfile(false)">保存</Button>
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.ai-model-picker {
  display: inline-flex;
  min-width: 0;
}
.ai-model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  max-width: 220px;
  padding: 3px 7px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: hsl(var(--muted-foreground));
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  line-height: 1.6;
}
.ai-model-trigger:hover,
.ai-model-trigger[aria-expanded='true'] {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}
.ai-model-trigger svg {
  width: 13px;
  height: 13px;
  flex: none;
}
.ai-model-trigger-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-model-trigger-effort {
  flex: none;
  padding: 0 4px;
  border-radius: 4px;
  background: hsl(var(--primary) / 12%);
  color: hsl(var(--primary));
  font-size: 10px;
}
.ai-model-menu {
  width: min(300px, calc(100vw - 48px));
  padding: 6px;
  color: hsl(var(--foreground));
  font-size: 13px;
}
.ai-model-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}
.ai-model-menu-current {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-model-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.ai-model-option:hover:not(:disabled),
.ai-model-option.is-current {
  background: hsl(var(--muted));
}
.ai-model-option:disabled {
  cursor: progress;
  opacity: 0.8;
}
.ai-model-option-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}
.ai-model-option-provider {
  color: hsl(var(--muted-foreground));
  font-size: 10px;
}
.ai-model-option-model {
  overflow: hidden;
  color: hsl(var(--foreground));
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-model-option-effort {
  color: hsl(var(--muted-foreground));
  font-size: 10px;
}
.ai-model-option-state {
  flex: none;
  color: hsl(var(--primary));
  font-size: 11px;
}
.ai-model-option svg {
  width: 16px;
  height: 16px;
  flex: none;
  color: hsl(var(--foreground));
}
.ai-model-menu-empty {
  margin: 4px 8px 8px;
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
.ai-model-menu-foot {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  padding: 6px 8px 2px;
  border-top: 1px solid hsl(var(--border));
}
.ai-model-effort {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}
.ai-model-effort-options {
  display: flex;
  gap: 2px;
}
.ai-model-effort-options button {
  min-width: 30px;
  padding: 2px 7px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: hsl(var(--muted-foreground));
  cursor: pointer;
  font: inherit;
  font-size: 11px;
}
.ai-model-effort-options button:hover:not(:disabled) {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}
.ai-model-effort-options button.is-active {
  background: hsl(var(--primary) / 12%);
  color: hsl(var(--primary));
}
.ai-model-effort-options button:disabled {
  cursor: default;
  opacity: 0.6;
}
.ai-model-config-link {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: transparent;
  color: hsl(var(--primary));
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.ai-model-config {
  display: grid;
  gap: 16px;
  grid-template-columns: 220px minmax(0, 1fr);
}
.ai-model-config-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 12px;
  border-right: 1px solid hsl(var(--border));
}
.ai-model-config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 9px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}
.ai-model-config-row:hover,
.ai-model-config-row.is-active {
  background: hsl(var(--muted));
}
.ai-model-config-row-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.ai-model-config-row-main strong {
  overflow: hidden;
  color: hsl(var(--foreground));
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-model-config-row-main small {
  overflow: hidden;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-model-badge {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: hsl(var(--primary) / 12%);
  color: hsl(var(--primary));
  font-size: 10px;
}
.ai-model-config-add {
  margin-top: 2px;
  padding: 7px 9px;
  border: 1px dashed hsl(var(--border));
  border-radius: 9px;
  background: transparent;
  color: hsl(var(--primary));
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}
.ai-model-config-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ai-model-field,
.ai-model-field-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-model-field > span {
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
.ai-model-field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.ai-model-hint {
  margin: 0;
  color: hsl(var(--muted-foreground));
  font-size: 11px;
  line-height: 1.6;
}
.ai-model-config-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 2px;
}
.ai-model-actions-spacer {
  flex: 1;
}
</style>
