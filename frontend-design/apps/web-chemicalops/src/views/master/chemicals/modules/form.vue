<script lang="ts" setup>
import type { ChemicalApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { useVbenForm } from '#/adapter/form';
import { createChemicalApi, updateChemicalApi } from '#/api';

import { useFormSchema } from '../data';

const emit = defineEmits(['success']);

const formData = ref<ChemicalApi.Chemical>();
const id = ref<number>();

const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  schema: useFormSchema(),
  showDefaultActions: false,
  wrapperClass: 'grid-cols-2',
});

const [Drawer, drawerApi] = useVbenDrawer<null | ChemicalApi.Chemical>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues();
    drawerApi.lock();
    try {
      if (id.value) {
        await updateChemicalApi(id.value, values);
      } else {
        await createChemicalApi(values as ChemicalApi.ChemicalPayload);
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
    formApi.reset();

    if (data) {
      formData.value = data;
      id.value = data.id;
    } else {
      formData.value = undefined;
      id.value = undefined;
    }

    // 等待表单字段挂载后再回填，避免部分字段被重置
    await nextTick();
    if (data) {
      formApi.setValues(data);
    }
  },
});

const title = computed(() =>
  id.value ? '编辑化学品' : '新增化学品',
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[640px]">
    <Form />
  </Drawer>
</template>
