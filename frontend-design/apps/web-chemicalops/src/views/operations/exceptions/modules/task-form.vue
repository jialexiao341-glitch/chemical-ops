<script lang="ts" setup>
import { computed, ref } from 'vue';

import { useVbenModal } from '@vben/common-ui';

import { DatePicker, Input, message, Select } from 'antdv-next';

import { createTaskApi, getUserListApi } from '#/api';
import { PRIORITY_DICT } from '#/constants/dictionary';

const emit = defineEmits(['success']);

/** 新建异常处理任务；创建后后端会把 OPEN/RESOLVED 异常推进为 PROCESSING */
const exceptionId = ref<number>();
const title = ref('');
const assigneeId = ref<number>();
const priority = ref('NORMAL');
const dueAt = ref<string>();
const userOptions = ref<Array<{ label: string; value: number }>>([]);
const loadingUsers = ref(false);

const [Modal, modalApi] = useVbenModal<null | { id: number }>({
  async onConfirm() {
    if (!title.value.trim()) {
      message.warning('请填写任务标题');
      return;
    }
    if (!exceptionId.value) {
      return;
    }
    modalApi.lock();
    try {
      await createTaskApi(exceptionId.value, {
        assignee_id: assigneeId.value,
        due_at: dueAt.value ? `${dueAt.value}:00` : undefined,
        priority: priority.value,
        title: title.value.trim(),
      });
      message.success('任务已创建');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开。
    } finally {
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    exceptionId.value = modalApi.getData()?.id;
    title.value = '';
    assigneeId.value = undefined;
    priority.value = 'NORMAL';
    dueAt.value = undefined;
    if (userOptions.value.length > 0) {
      return;
    }
    loadingUsers.value = true;
    try {
      const res = await getUserListApi({ page: 1, page_size: 100 });
      userOptions.value = res.items
        .filter((item) => !item.status || item.status === 'ACTIVE')
        .map((item) => ({
          label: `${item.display_name || item.username}（${item.username}）`,
          value: item.id,
        }));
    } finally {
      loadingUsers.value = false;
    }
  },
});

const titleText = computed(() => '新建处理任务');
</script>

<template>
  <Modal :title="titleText" class="w-[520px]">
    <div class="space-y-4 px-1">
      <div>
        <div class="mb-2 text-sm">
          任务标题 <span class="text-red-500">*</span>
        </div>
        <Input
          v-model:value="title"
          :maxlength="255"
          placeholder="例如：与供应商核实短交数量"
        />
      </div>
      <div>
        <div class="mb-2 text-sm">负责人</div>
        <Select
          v-model:value="assigneeId"
          :loading="loadingUsers"
          :options="userOptions"
          allow-clear
          class="w-full"
          placeholder="可指派给具体处理人"
          show-search
        />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <div class="mb-2 text-sm">优先级</div>
          <Select
            v-model:value="priority"
            :options="PRIORITY_DICT.options()"
            class="w-full"
          />
        </div>
        <div>
          <div class="mb-2 text-sm">截止时间</div>
          <DatePicker
            v-model:value="dueAt"
            class="w-full"
            show-time
            value-format="YYYY-MM-DDTHH:mm"
          />
        </div>
      </div>
    </div>
  </Modal>
</template>
