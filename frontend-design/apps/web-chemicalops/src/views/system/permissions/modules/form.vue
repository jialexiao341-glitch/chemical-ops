<script lang="ts" setup>
import type { SystemPermissionApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import { createPermissionApi, updatePermissionApi } from '#/api';

import { useFormSchema } from '../data';

const emit = defineEmits(['success']);

const id = ref<number>();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: useFormSchema(),
  showDefaultActions: false,
  wrapperClass: 'grid-cols-1 sm:grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | SystemPermissionApi.SystemPermission>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        // 权限编码是唯一标识，更新时不提交
        const { permission_code: _ignored, ...payload } = values as any;
        await updatePermissionApi(id.value, payload);
      } else {
        await createPermissionApi(
          values as SystemPermissionApi.PermissionPayload,
        );
      }
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会导致未捕获的 Promise 拒绝。
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    formApi.reset();
    id.value = data?.id;

    await nextTick();
    if (data) {
      formApi.setValues(data);
    }
  },
});

const title = computed(() => (id.value ? '编辑权限' : '新增权限'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[640px] max-w-[100vw]">
    <Form />
  </Drawer>
</template>
