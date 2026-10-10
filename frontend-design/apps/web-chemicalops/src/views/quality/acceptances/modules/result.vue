<script lang="ts" setup>
import type { QualityAcceptanceApi } from '#/api';

import { computed, nextTick, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';

import { Alert, Button, Input, Select, message } from 'antdv-next';

import { useVbenForm } from '#/adapter/form';
import { getAcceptanceReportFilesApi, getAcceptanceReviewTargetsApi, submitAcceptanceResultApi } from '#/api';
import { ACCEPTANCE_RESULT_DICT } from '#/constants/dictionary';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['quality.acceptances.write']));
const emit = defineEmits(['success', 'review']);

interface ResultDrawerData extends QualityAcceptanceApi.Acceptance {
  suggested_report_file_id?: number;
  suggested_test_result?: Record<string, string>;
}

const acceptance = ref<null | ResultDrawerData>();
const reportFiles = ref<QualityAcceptanceApi.ReportFile[]>([]);
const selectedReportFileId = ref<number>();
const hasAiSuggestion = ref(false);
const targets = ref<QualityAcceptanceApi.ReviewTarget[]>([]);
const targetsLoaded = ref(false);
const itemRows = ref<Record<number, { name: string; value: string }[]>>({});

function addTestItem(deliveryItemId: number) {
  (itemRows.value[deliveryItemId] ??= []).push({ name: '', value: '' });
}

function rowsFromSaved(value: unknown): { name: string; value: string }[] {
  if (Array.isArray(value)) {
    return value.filter((row) => row && typeof row === 'object').map((row) => ({
      name: String(row.name ?? row.item ?? ''), value: String(row.value ?? row.result ?? ''),
    }));
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([name, result]) => ({ name, value: String(result ?? '') }));
  }
  return [];
}

function openReportReview() {
  if (!acceptance.value) return;
  drawerApi.close();
  emit('review', acceptance.value);
}

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
        // PENDING 是「尚未录入」的初始态，不是可提交的结果，排除掉
        options: ACCEPTANCE_RESULT_DICT.options().filter(
          (item) => item.value !== 'PENDING',
        ),
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
  ],
});

const [Drawer, drawerApi] = useVbenDrawer<null | ResultDrawerData>({
  async onConfirm() {
    if (!canConfirm.value) return;
    const { valid } = await formApi.validate();
    if (!valid) {
      return;
    }
    const values = await formApi.getValues<any>();
    if (!targetsLoaded.value || targets.value.length === 0) {
      message.warning('到货明细尚未加载，暂不能提交验收结果');
      return;
    }
    let itemResults: QualityAcceptanceApi.ResultPayload['item_results'];
    if (values.result !== 'REINSPECTION' && targets.value.length) {
      itemResults = [];
      for (const target of targets.value) {
        const rows = itemRows.value[target.delivery_item_id] ?? [];
        const tests: Record<string, string> = {};
        for (const row of rows) {
          const name = row.name.trim();
          const value = row.value.trim();
          if (!name || !value || name in tests) {
            message.warning(`请检查第 ${target.line_no} 条到货明细的检测项目和值，项目名称不能重复`);
            return;
          }
          tests[name] = value;
        }
        if (targets.value.length > 1 && rows.length === 0) {
          message.warning(`请填写第 ${target.line_no} 条到货明细的检测结果`);
          return;
        }
        if (rows.length) itemResults.push({ delivery_item_id: target.delivery_item_id, tests });
      }
      if (!itemResults.length) itemResults = undefined;
    }
    drawerApi.lock();
    try {
      await submitAcceptanceResultApi(acceptance.value!.id, {
        certificate_complete: Boolean(values.certificate_complete),
        conclusion: values.conclusion || undefined,
        report_file_id: selectedReportFileId.value,
        result: values.result,
        item_results: itemResults,
      });
      emit('success');
      drawerApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持抽屉打开，
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
    acceptance.value = data;
    hasAiSuggestion.value = Boolean(data?.suggested_test_result && Object.keys(data.suggested_test_result).length && !data.test_result);
    reportFiles.value = [];
    targets.value = [];
    targetsLoaded.value = false;
    itemRows.value = {};
    selectedReportFileId.value = data?.suggested_report_file_id ?? data?.report_file_id ?? undefined;
    formApi.reset();

    await nextTick();
    if (data) {
      const [filesResult, targetsResult] = await Promise.allSettled([
        getAcceptanceReportFilesApi(data.id),
        getAcceptanceReviewTargetsApi(data.id),
      ]);
      if (filesResult.status === 'fulfilled') reportFiles.value = filesResult.value;
      if (targetsResult.status === 'fulfilled') {
        targets.value = targetsResult.value;
        targetsLoaded.value = true;
      }
      if (targetsResult.status === 'rejected') message.warning('未能读取到货明细，请重试后再提交验收结果');
      if (filesResult.status === 'fulfilled') {
        selectedReportFileId.value ??= reportFiles.value[0]?.id;
      }
      const saved = data.test_result?.by_delivery_item ?? {};
      for (const target of targets.value) {
        const values = saved[String(target.delivery_item_id)] ?? (targets.value.length === 1 ? data.test_result ?? data.suggested_test_result : undefined);
        itemRows.value[target.delivery_item_id] = rowsFromSaved(values);
      }
      formApi.setValues({
        certificate_complete: Boolean(data.certificate_complete),
        conclusion: data.conclusion ?? undefined,
        result: data.result && !['PENDING', 'REINSPECTION'].includes(data.result)
          ? data.result
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
  <Drawer :show-confirm-button="canConfirm" :title="title" class="w-[640px] max-w-[100vw]">
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
      <Alert
        v-if="hasAiSuggestion"
        message="已带入报告提取的候选检测值。请逐项对照原始报告，必要时修改后再提交。"
        type="info"
        show-icon
      />
      <div class="flex justify-end">
        <Button @click="openReportReview">先核对报告</Button>
      </div>
      <Form />
      <div v-if="targets.length" class="space-y-4">
        <h3 class="text-sm font-semibold">按到货明细录入检测结果</h3>
        <div v-for="target in targets" :key="target.delivery_item_id" class="space-y-2 rounded-lg border border-border p-3">
          <div class="text-sm font-medium">{{ target.line_no }}. {{ target.product_name }} · {{ target.batch_no || '无批次' }}</div>
          <div v-for="(row, index) in itemRows[target.delivery_item_id] ?? []" :key="index" class="flex gap-2">
            <Input v-model:value="row.name" aria-label="检测项目" placeholder="检测项目" />
            <Input v-model:value="row.value" aria-label="检测值及单位" placeholder="检测值及单位" />
            <Button @click="itemRows[target.delivery_item_id]?.splice(index, 1)">移除</Button>
          </div>
          <Button @click="addTestItem(target.delivery_item_id)">添加检测项</Button>
        </div>
      </div>
      <div>
        <label class="mb-1 block text-sm">检测报告</label>
        <Select
          v-model:value="selectedReportFileId"
          class="w-full"
          allow-clear
          placeholder="选择已关联的报告（可选）"
          :options="reportFiles.map((item) => ({ label: item.file_name, value: item.id }))"
        />
        <p class="mt-1 text-xs text-muted-foreground">可先在验收列表中使用“核对报告”上传并复核。</p>
      </div>
    </div>
  </Drawer>
</template>
