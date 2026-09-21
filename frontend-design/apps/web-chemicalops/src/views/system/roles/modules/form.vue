<script lang="ts" setup>
import type { SystemRoleApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import { createRoleApi, updateRoleApi } from '#/api';

import { useCreateFormSchema, useUpdateFormSchema } from '../data';

const emit = defineEmits(['success']);

const id = ref<number>();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: [],
  showDefaultActions: false,
  wrapperClass: 'grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | SystemRoleApi.SystemRole>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        // 后端未返回角色已有权限，留空时不提交 permission_ids，避免清空绑定
        const payload: Record<string, any> = { ...values };
        if (
          !Array.isArray(payload.permission_ids) ||
          payload.permission_ids.length === 0
        ) {
          delete payload.permission_ids;
        }
        await updateRoleApi(id.value, payload);
      } else {
        await createRoleApi(values as SystemRoleApi.RolePayload);
      }
      emit('success');
      drawerApi.close();
    } finally {
      drawerApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    id.value = data?.id;
    formApi.setState({
      schema: data ? useUpdateFormSchema() : useCreateFormSchema(),
    });
    formApi.reset();

    await nextTick();
    if (data) {
      formApi.setValues({
        description: data.description ?? undefined,
        role_code: data.role_code,
        role_name: data.role_name,
        status: data.status,
      });
    }
  },
});

const title = computed(() => (id.value ? '编辑角色' : '新增角色'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[680px]">
    <div
      v-if="id"
      class="bg-accent text-muted-foreground mb-4 rounded-md px-3 py-2 text-xs"
    >
      权限留空表示保持原有权限绑定不变。
    </div>
    <Form />
  </Drawer>
</template>
