<script lang="ts" setup>
import type { QualityAcceptanceApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Alert } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { submitAcceptanceResultApi } from '#/api';
import { ACCEPTANCE_RESULT_DICT } from '#/constants/dictionary';

const emit = defineEmits(['success']);

const acceptance = ref<null | QualityAcceptanceApi.Acceptance>();

/**
 * 录入质量验收结果。
 *
 * 结果为「合格」时到货单进入已验收；「部分合格 / 不合格」会进入异常
 * 并自动创建质量异常单；已完成验收的记录只能先提交「待复检」再录入新结果。
 */
const [Form, formApi] = useVbenForm({
  layout: 'vertical',
  showDefaultActions: false,
  schema: [
    {
      component: 'RadioGroup',
      componentProps: {
        buttonStyle: 'solid',
        options: ACCEPTANCE_RESULT_DICT.options(),
        optionType: 'button',
      },
      fieldName: 'result',
      label: '验收结果',
      rules: 'selectRequired',
    },
    {
      component: 'Switch',
      componentProps: {
        checkedChildren: '齐全',
        unCheckedChildren: '不齐全',
      },
      defaultValue: false,
      fieldName: 'certificate_complete',
      label: '单证是否齐全',
    },
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 1000,
        placeholder: '例如：各项指标符合国标，杂质含量低于上限',
        rows: 3,
      },
      fieldName: 'conclusion',
      label: '验收结论',
    },
    {
      component: 'Textarea',
      componentProps: {
        maxlength: 2000,
        placeholder: '可填写 JSON，例如 {"纯度": "99.5%", "水分": "0.02%"}',
        rows: 4,
      },
      fieldName: 'test_result_text',
      help: '检测数据，按 JSON 格式填写；留空表示不记录检测项。',
      label: '检测数据（JSON）',
    },
  ],
});

const [Drawer, drawerApi] = useVbenDrawer<null | QualityAcceptanceApi.Acceptance>({
  async onConfirm() {
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues<any>();
    // 检测数据按 JSON 解析，格式不合法时直接提示，避免提交脏数据
    let testResult: any;
    const raw = String(values.test_result_text ?? '').trim();
    if (raw) {
      try {
        testResult = JSON.parse(raw);
      } catch {
        formApi.setFieldError('test_result_text', '不是合法的 JSON');
        return;
      }
    }
    drawerApi.lock();
    try {
      await submitAcceptanceResultApi(acceptance.value!.id, {
        certificate_complete: Boolean(values.certificate_complete),
        conclusion: values.conclusion || undefined,
        report_file_id: acceptance.value?.report_file_id ?? undefined,
        result: values.result,
        test_result: testResult,
      });
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
    acceptance.value = data;
    formApi.reset();

    await nextTick();
    if (data) {
      formApi.setValues({
        certificate_complete: Boolean(data.certificate_complete),
        conclusion: data.conclusion ?? undefined,
        result: data.result ?? undefined,
        test_result_text: data.test_result
          ? JSON.stringify(data.test_result, null, 2)
          : undefined,
      });
    }
  },
});

const title = computed(
  () => `录入验收结果 · ${acceptance.value?.acceptance_no ?? ''}`,
);

/** 复检场景需要额外提示 */
const needReinspectionHint = computed(() => acceptance.value?.result === 'REINSPECTION');

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="title" class="w-[640px]">
    <div class="space-y-4">
      <Alert
        v-if="needReinspectionHint"
        message="该验收单当前为待复检状态，录入新的最终结果后将覆盖当前结论。"
        type="info"
        show-icon
      />
      <Alert
        message="选择「部分合格」或「不合格」时，系统会自动创建质量异常单并通知采购经理与质量人员。"
        type="warning"
        show-icon
      />
      <Form />
    </div>
  </Drawer>
</template>
