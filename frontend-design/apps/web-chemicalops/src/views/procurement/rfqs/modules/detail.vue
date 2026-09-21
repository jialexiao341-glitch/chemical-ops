<script lang="ts" setup>
import type { RfqApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer, useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Button,
  Descriptions,
  DescriptionsItem,
  Empty,
  Spin,
  TabPane,
  Table,
  Tabs,
  Tag,
  message,
} from 'antdv-next';

import {
  buildComparisonApi,
  createPurchaseOrderApi,
  getComparisonApi,
  getRfqApi,
  sendRfqApi,
} from '#/api';
import {
  COMPARISON_STATUS_DICT,
  QUOTE_STATUS_DICT,
  RFQ_STATUS_DICT,
} from '#/constants/dictionary';
import { formatAmount, formatDateTime, formatQuantity } from '#/utils/format';
import { getSupplierNameMap } from '#/utils/lookup';

import SelectQuoteModal from './select-quote.vue';

const emit = defineEmits(['success']);

const detail = ref<RfqApi.Rfq>();
const comparison = ref<RfqApi.QuoteComparison>();
const loading = ref(false);
const acting = ref(false);
const supplierMap = ref<Map<number, string>>(new Map());
const activeTab = ref('items');

const [SelectQuote, selectQuoteApi] = useVbenModal({
  connectedComponent: SelectQuoteModal,
  destroyOnClose: true,
});

const [Drawer, drawerApi] = useVbenDrawer<null | RfqApi.Rfq>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    detail.value = undefined;
    comparison.value = undefined;
    activeTab.value = 'items';
    if (!data?.id) {
      return;
    }
    loading.value = true;
    try {
      await reload(data.id);
    } finally {
      loading.value = false;
    }
  },
});

/** 重新拉取询价单与比价单 */
async function reload(rfqId?: number) {
  const id = rfqId ?? detail.value?.id;
  if (!id) {
    return;
  }
  const [rfq, suppliers] = await Promise.all([
    getRfqApi(id),
    getSupplierNameMap(),
  ]);
  detail.value = rfq;
  supplierMap.value = suppliers;
  // 比价单可能尚未生成，404 不作为错误处理
  try {
    comparison.value = await getComparisonApi(id);
  } catch {
    comparison.value = undefined;
  }
}

function supplierName(id?: null | number) {
  if (!id) {
    return '-';
  }
  return supplierMap.value.get(id) ?? `供应商 #${id}`;
}

function quoteSupplierId(quoteId: number) {
  return detail.value?.quotes?.find((item) => item.id === quoteId)?.supplier_id;
}

async function onSend() {
  if (!detail.value?.id) {
    return;
  }
  acting.value = true;
  try {
    await sendRfqApi(detail.value.id);
    message.success('询价单已发送');
    await reload();
    emit('success');
  } finally {
    acting.value = false;
  }
}

async function onBuildComparison() {
  if (!detail.value?.id) {
    return;
  }
  acting.value = true;
  try {
    comparison.value = await buildComparisonApi(detail.value.id);
    message.success('比价已生成');
    activeTab.value = 'comparison';
    await reload();
    emit('success');
  } finally {
    acting.value = false;
  }
}

function onSelectQuote(record: RfqApi.ComparisonItem) {
  if (!detail.value?.id || !comparison.value?.id) {
    return;
  }
  selectQuoteApi
    .setData({
      comparisonId: comparison.value.id,
      quoteId: record.quote_id,
      rfqId: detail.value.id,
      supplierName: supplierName(record.supplier_id),
      totalAmount: record.total_amount,
      unitPrice: record.quoted_unit_price,
    })
    .open();
}

async function onSelectSuccess() {
  await reload();
  emit('success');
}

/** 依据中选报价生成采购订单草稿 */
async function onCreateOrder() {
  if (!detail.value?.id || !comparison.value?.selected_quote_id) {
    message.warning('请先确认中选报价');
    return;
  }
  acting.value = true;
  try {
    await createPurchaseOrderApi({
      comparison_id: comparison.value.id,
      quote_id: comparison.value.selected_quote_id,
    });
    message.success('采购订单草稿已生成，请到采购订单页面提交审批');
    emit('success');
  } finally {
    acting.value = false;
  }
}

const canSend = computed(() => detail.value?.status === 'DRAFT');
const canCompare = computed(
  () =>
    (detail.value?.quotes?.length ?? 0) > 0 && detail.value?.status !== 'CLOSED',
);
const canCreateOrder = computed(
  () =>
    !!comparison.value?.selected_quote_id &&
    comparison.value?.status === 'CONFIRMED',
);

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'requested_name', title: '物料', minWidth: 160 },
  { key: 'specification', title: '规格', width: 140 },
  { key: 'quantity', title: '数量', width: 110, align: 'right' as const },
  { key: 'required_delivery_date', title: '要求到货', width: 120 },
];

const quoteColumns = [
  { key: 'quote_no', title: '报价单号', minWidth: 170 },
  { key: 'supplier_id', title: '供应商', minWidth: 160 },
  { key: 'quote_version', title: '版本', width: 70 },
  { key: 'quote_date', title: '报价日期', width: 120 },
  { key: 'valid_until', title: '有效期至', width: 120 },
  { key: 'status', title: '状态', width: 100 },
];

const comparisonColumns = [
  { key: 'supplier_id', title: '供应商', minWidth: 160 },
  {
    key: 'quoted_unit_price',
    title: '单价',
    width: 140,
    align: 'right' as const,
  },
  { key: 'total_amount', title: '金额', width: 140, align: 'right' as const },
  { key: 'lead_days', title: '交期(天)', width: 100 },
  { key: 'moq_quantity', title: '最小起订量', width: 120 },
  { key: 'payment_terms', title: '付款条件', width: 140 },
  { key: 'rank_no', title: '排名', width: 90 },
  { key: 'selection_flag', title: '中选', width: 90 },
  { key: '__action', title: '操作', width: 120 },
];

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="`询价单 ${detail?.rfq_no ?? ''}`" class="w-[1100px]">
    <SelectQuote @success="onSelectSuccess" />
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该询价单" />
      <div v-else-if="detail" class="space-y-5">
        <Descriptions bordered :column="3" size="small">
          <DescriptionsItem label="状态">
            <Tag :color="RFQ_STATUS_DICT.color(detail.status)">
              {{ RFQ_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="来源申请">
            {{ detail.source_request_id ?? '-' }}
          </DescriptionsItem>
          <DescriptionsItem label="报价截止">
            {{ formatDateTime(detail.quote_deadline) }}
          </DescriptionsItem>
          <DescriptionsItem label="受邀供应商">
            {{ detail.suppliers?.length ?? 0 }} 家
          </DescriptionsItem>
          <DescriptionsItem label="已收报价">
            {{ detail.quotes?.length ?? 0 }} 份
          </DescriptionsItem>
          <DescriptionsItem label="交付要求">
            {{ detail.delivery_requirements || '-' }}
          </DescriptionsItem>
        </Descriptions>

        <div class="flex flex-wrap gap-2">
          <Button v-if="canSend" :loading="acting" type="primary" @click="onSend">
            发送询价单
          </Button>
          <Button v-if="canCompare" :loading="acting" @click="onBuildComparison">
            生成比价
          </Button>
          <Button
            v-if="canCreateOrder"
            :loading="acting"
            type="primary"
            @click="onCreateOrder"
          >
            依据中选报价生成采购订单
          </Button>
        </div>

        <Alert
          v-if="comparison?.selected_quote_id"
          :message="`已中选：${supplierName(quoteSupplierId(comparison.selected_quote_id))}${comparison.selection_reason ? ` · ${comparison.selection_reason}` : ''}`"
          type="success"
          show-icon
        />

        <Tabs v-model:active-key="activeTab">
          <TabPane key="items" tab="询价明细">
            <Table
              :columns="itemColumns"
              :data-source="detail.items ?? []"
              :pagination="false"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'quantity'">
                  {{ formatQuantity(record.quantity) }}
                </template>
                <template v-else-if="column.key === 'required_delivery_date'">
                  {{ record.required_delivery_date ?? '-' }}
                </template>
              </template>
            </Table>
          </TabPane>

          <TabPane
            key="quotes"
            :tab="`供应商报价 (${detail.quotes?.length ?? 0})`"
          >
            <Empty
              v-if="(detail.quotes ?? []).length === 0"
              description="还没有收到报价"
            />
            <Table
              v-else
              :columns="quoteColumns"
              :data-source="detail.quotes ?? []"
              :pagination="false"
              row-key="id"
              size="small"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'supplier_id'">
                  {{ supplierName(record.supplier_id) }}
                </template>
                <template v-else-if="column.key === 'status'">
                  <Tag :color="QUOTE_STATUS_DICT.color(record.status)">
                    {{ QUOTE_STATUS_DICT.label(record.status) }}
                  </Tag>
                </template>
              </template>
            </Table>
          </TabPane>

          <TabPane key="comparison" tab="报价比较">
            <Empty
              v-if="!comparison"
              description="还没有生成比价，请先点击「生成比价」"
            />
            <div v-else class="space-y-3">
              <div class="flex items-center gap-3">
                <span class="text-sm">比价单：{{ comparison.comparison_no }}</span>
                <Tag :color="COMPARISON_STATUS_DICT.color(comparison.status)">
                  {{ COMPARISON_STATUS_DICT.label(comparison.status) }}
                </Tag>
              </div>
              <Table
                :columns="comparisonColumns"
                :data-source="comparison.items ?? []"
                :pagination="false"
                :scroll="{ x: 1200 }"
                row-key="id"
                size="small"
              >
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'supplier_id'">
                    {{ supplierName(record.supplier_id) }}
                  </template>
                  <template v-else-if="column.key === 'quoted_unit_price'">
                    {{ formatAmount(record.quoted_unit_price, 6) }}
                  </template>
                  <template v-else-if="column.key === 'total_amount'">
                    {{ formatAmount(record.total_amount) }}
                  </template>
                  <template v-else-if="column.key === 'moq_quantity'">
                    {{ formatQuantity(record.moq_quantity) }}
                  </template>
                  <template v-else-if="column.key === 'lead_days'">
                    {{ record.lead_days ?? '-' }}
                  </template>
                  <template v-else-if="column.key === 'payment_terms'">
                    {{ record.payment_terms || '-' }}
                  </template>
                  <template v-else-if="column.key === 'rank_no'">
                    <Tag :color="record.rank_no === 1 ? 'success' : 'default'">
                      第 {{ record.rank_no ?? '-' }} 名
                    </Tag>
                  </template>
                  <template v-else-if="column.key === 'selection_flag'">
                    <Tag v-if="record.selection_flag" color="success">已中选</Tag>
                    <span v-else class="text-muted-foreground">-</span>
                  </template>
                  <template v-else-if="column.key === '__action'">
                    <Button
                      v-if="comparison?.status !== 'CONFIRMED'"
                      size="small"
                      type="link"
                      @click="onSelectQuote(record)"
                    >
                      选为中标
                    </Button>
                  </template>
                </template>
              </Table>
            </div>
          </TabPane>
        </Tabs>
      </div>
    </Spin>
  </Drawer>
</template>
