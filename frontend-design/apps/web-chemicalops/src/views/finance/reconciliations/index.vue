<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  confirmReconciliationApi,
  disputeReconciliationApi,
  getReconciliationListApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import FinanceSourceDetail from '#/views/ai/workspace/modules/finance-source-detail.vue';

defineOptions({ name: 'ReconciliationList' });
const route = useRoute();
const financeSourceDetail = ref<InstanceType<typeof FinanceSourceDetail>>();

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

/** 争议弹窗（原因必填） */
const disputeVisible = ref(false);
const disputeReason = ref('');
const disputeRow = ref<FinanceApi.Reconciliation>();

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveSupplier.value(id)),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getReconciliationListApi({
            page: page.currentPage,
            page_size: page.pageSize,
            ...formValues,
          });
        },
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: {
      custom: true,
      export: false,
      refresh: true,
      search: true,
      zoom: true,
    },
  } as VxeTableGridOptions<FinanceApi.Reconciliation>,
});

function runConfirm(row: FinanceApi.Reconciliation) {
  Modal.confirm({
    content: `确认对账单 ${row.reconciliation_no}？确认后才能录入发票和发起付款。`,
    okText: '确认对账',
    onOk: async () => {
      await confirmReconciliationApi(row.id);
      message.success('对账单已确认');
      gridApi.query();
    },
    title: '确认对账单',
  });
}

function openDispute(row: FinanceApi.Reconciliation) {
  disputeRow.value = row;
  disputeReason.value = '';
  disputeVisible.value = true;
}

async function onDisputeConfirm() {
  if (!disputeReason.value.trim()) {
    message.warning('请填写争议原因');
    return;
  }
  if (!disputeRow.value) {
    return;
  }
  try {
    await disputeReconciliationApi(disputeRow.value.id, disputeReason.value.trim());
    message.success('已发起对账争议');
    disputeVisible.value = false;
    gridApi.query();
  } catch {
    // 请求层已弹出错误，保持弹窗打开
  }
}

onMounted(async () => {
  try {
    const suppliers = await getSupplierNameMap();
    resolveSupplier.value = (id) => {
      if (!id) {
        return '-';
      }
      return suppliers.get(id) ?? `#${id}`;
    };
  } catch {
    resolveSupplier.value = (id) => (id ? `#${id}` : '-');
  }
  await applyAiFiltersToList(
    'finance_reconciliations',
    route.query.ai_filters,
    gridApi.formApi,
  );
  gridApi.query();
  openAiFinanceRecord(route.query.ai_record_id, route.query.ai_record_type);
});

function openAiFinanceRecord(rawId: unknown, rawType: unknown) {
  const id = Number(rawId);
  if (rawType !== 'reconciliations' || !Number.isInteger(id) || id <= 0) return;
  financeSourceDetail.value?.open({ id, kind: 'reconciliations' });
}

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (
      await applyAiFiltersToList(
        'finance_reconciliations',
        rawQuery,
        gridApi.formApi,
      )
    ) {
      gridApi.query();
    }
  },
);

watch(
  () => [route.query.ai_record_id, route.query.ai_record_type],
  ([id, kind]) => openAiFinanceRecord(id, kind),
);
</script>

  <template>
  <Page auto-content-height>
    <FinanceSourceDetail ref="financeSourceDetail" />
    <Create @success="gridApi.query()" />
    <Grid table-title="财务对账">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          创建对账单
        </Button>
      </template>
      <template #operation="{ row }">
        <div class="flex flex-wrap justify-center gap-0">
          <Button
            v-if="['DRAFT', 'DISPUTED'].includes(row.status)"
            size="small"
            type="link"
            @click="runConfirm(row)"
          >
            确认对账
          </Button>
          <Button
            v-if="['DRAFT', 'CONFIRMED'].includes(row.status)"
            danger
            size="small"
            type="link"
            @click="openDispute(row)"
          >
            发起争议
          </Button>
        </div>
      </template>
    </Grid>

    <!-- 争议弹窗（原因必填） -->
    <Modal
      v-model:open="disputeVisible"
      cancel-text="取消"
      ok-text="确认发起"
      title="发起对账争议"
      @ok="onDisputeConfirm"
    >
      <div class="py-2">
        <div class="mb-2 text-sm">
          争议原因 <span class="text-red-500">*</span>
        </div>
        <Input.TextArea
          v-model:value="disputeReason"
          :maxlength="1000"
          :rows="3"
          placeholder="请说明对账差异或争议内容（必填）"
        />
      </div>
    </Modal>
  </Page>
</template>
