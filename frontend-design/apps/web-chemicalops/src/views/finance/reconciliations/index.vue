<script lang="ts" setup>
import type { VxeTableGridOptions } from '#/adapter/vxe-table';
import type { FinanceApi, SupplierPortalApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';

import { Button, Empty, Input, message, Modal, Spin, Tag } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  confirmReconciliationApi,
  disputeReconciliationApi,
  getReconciliationListApi,
  addFinanceSupplierReconciliationMessageApi,
  getFinanceSupplierReconciliationMessagesApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';
import { RECONCILIATION_STATUS_DICT } from '#/constants/dictionary';
import { formatAmount, formatDateTime } from '#/utils/format';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import ItemsDrawer from './modules/items.vue';
import FinanceSourceDetail from '#/views/ai/workspace/modules/finance-source-detail.vue';

defineOptions({ name: 'ReconciliationList' });
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const [Items, itemsApi] = useVbenDrawer({ connectedComponent: ItemsDrawer, destroyOnClose: true });
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
const collaborationVisible = ref(false);
const collaborationRow = ref<FinanceApi.Reconciliation>();
const collaborationMessages = ref<SupplierPortalApi.ReconciliationMessage[]>([]);
const collaborationDraft = ref('');
const collaborationLoading = ref(false);
const collaborationSending = ref(false);

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns((id) => resolveSupplier.value(id), onActionClick),
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

function onActionClick({ code, row }: { code: string; row: FinanceApi.Reconciliation }) {
  if (code === 'items') itemsApi.setData(row.id).open();
  else if (code === 'collaboration') void openSupplierCollaboration(row);
  else if (code === 'confirm') runConfirm(row);
  else if (code === 'dispute') openDispute(row);
}

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

async function openSupplierCollaboration(row: FinanceApi.Reconciliation) {
  collaborationRow.value = row;
  collaborationDraft.value = '';
  collaborationVisible.value = true;
  collaborationLoading.value = true;
  try {
    const result = await getFinanceSupplierReconciliationMessagesApi(row.id);
    collaborationMessages.value = result.items;
  } finally {
    collaborationLoading.value = false;
  }
}

async function sendSupplierMessage() {
  const row = collaborationRow.value;
  const text = collaborationDraft.value.trim();
  if (!row || !text || collaborationSending.value) return;
  collaborationSending.value = true;
  try {
    await addFinanceSupplierReconciliationMessageApi(row.id, text);
    collaborationDraft.value = '';
    const result = await getFinanceSupplierReconciliationMessagesApi(row.id);
    collaborationMessages.value = result.items;
    message.success('协同留言已发送');
  } finally {
    collaborationSending.value = false;
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
    <Items @success="gridApi.query()" />
    <Grid table-title="财务对账">
      <template #toolbar-tools>
        <Button v-if="hasAccessByCodes(['finance.reconciliations.write'])" type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          创建对账单
        </Button>
      </template>
    </Grid>

    <Modal v-model:open="collaborationVisible" :footer="null" title="供应商对账协同" width="720px">
      <div v-if="collaborationRow" class="space-y-4 py-2">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
          <div>
            <div class="font-semibold">{{ collaborationRow.reconciliation_no }}</div>
            <div class="text-sm text-muted-foreground">{{ resolveSupplier(collaborationRow.supplier_id) }} · {{ formatAmount(collaborationRow.total_amount) }} {{ collaborationRow.currency_code }}</div>
          </div>
          <Tag :color="RECONCILIATION_STATUS_DICT.color(collaborationRow.status)">{{ RECONCILIATION_STATUS_DICT.label(collaborationRow.status) }}</Tag>
        </div>
        <Spin :spinning="collaborationLoading">
          <div class="max-h-80 space-y-3 overflow-y-auto rounded-md bg-muted/30 p-3">
            <Empty v-if="collaborationMessages.length === 0" description="暂无协同留言" />
            <div v-for="item in collaborationMessages" :key="item.id" class="rounded-md border bg-background p-3">
              <div class="mb-1 flex justify-between gap-3 text-xs text-muted-foreground"><span>{{ item.author_type === 'SUPPLIER' ? '供应商' : '我方' }}</span><span>{{ formatDateTime(item.created_at) }}</span></div>
              <div class="whitespace-pre-wrap text-sm">{{ item.message }}</div>
            </div>
          </div>
        </Spin>
        <div v-if="hasAccessByCodes(['finance.reconciliations.write'])" class="flex items-end gap-2">
          <Input.TextArea v-model:value="collaborationDraft" :maxlength="2000" :rows="2" placeholder="输入对账说明或回复供应商" />
          <Button type="primary" :loading="collaborationSending" :disabled="!collaborationDraft.trim()" @click="sendSupplierMessage">发送</Button>
        </div>
      </div>
    </Modal>

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
