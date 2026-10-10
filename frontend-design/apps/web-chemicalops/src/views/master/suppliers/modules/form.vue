<script lang="ts" setup>
import type { SupplierApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import { createSupplierApi, updateSupplierApi } from '#/api';

import { useFormSchema } from '../data';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['master.suppliers.write']));
const emit = defineEmits(['success']);

const id = ref<number>();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: useFormSchema(),
  showDefaultActions: false,
  wrapperClass: 'grid-cols-1 sm:grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | SupplierApi.Supplier>({
  async onConfirm() {
    if (!canConfirm.value) return;
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        await updateSupplierApi(id.value, values);
      } else {
        await createSupplierApi(values as SupplierApi.SupplierPayload);
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

const title = computed(() => (id.value ? '编辑供应商' : '新增供应商'));

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :show-confirm-button="canConfirm" :title="title" class="w-[720px] max-w-[100vw]">
    <Form />
  </Drawer>
</template>
