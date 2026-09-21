<script lang="ts" setup>
import type { SystemDepartmentApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import { createDepartmentApi, updateDepartmentApi } from '#/api';

import { useCreateFormSchema, useUpdateFormSchema } from '../data';

const emit = defineEmits(['success']);

const id = ref<number>();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: [],
  showDefaultActions: false,
  wrapperClass: 'grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | SystemDepartmentApi.SystemDepartment>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        const { department_code: _ignored, ...payload } = values as any;
        await updateDepartmentApi(id.value, payload);
      } else {
        await createDepartmentApi(
          values as SystemDepartmentApi.DepartmentPayload,
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
    id.value = data?.id;
    formApi.setState({
      schema: data
        ? useUpdateFormSchema(() => id.value)()
        : useCreateFormSchema(),
    });
    formApi.reset();

    await nextTick();
    if (data) {
      formApi.setValues({
        department_code: data.department_code,
        department_name: data.department_name,
        manager_id: data.manager_id ?? undefined,
        parent_id: data.parent_id ?? undefined,
        status: data.status,
      });
    }
  },
});

const title = computed(() => (id.value ? '编辑部门' : '新增部门'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[600px]">
    <Form />
  </Drawer>
</template>
