<script lang="ts" setup>
import type { RfqApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer, useVbenModal } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import {
  Alert,
  Button,
  Descriptions,
  DescriptionsItem,
  Empty,
  InputNumber,
  Modal,
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
  createActionProposalApi,
  confirmActionProposalApi,
} from '#/api';
import { canConfirmActionProposal } from '#/views/ai/workspace/action-proposal-policy';
import {
  COMPARISON_STATUS_DICT,
  QUOTE_STATUS_DICT,
  RFQ_STATUS_DICT,
} from '#/constants/dictionary';
import { formatAmount, formatDate, formatDateTime, formatQuantity } from '#/utils/format';
import { getSupplierNameMap } from '#/utils/lookup';

import QuoteModal from './quote.vue';
import SelectQuoteModal from './select-quote.vue';
import BusinessInsightDrawer from '#/views/ai/workspace/modules/business-insight-drawer.vue';

const emit = defineEmits(['success']);
const { hasAccessByCodes } = useAccess();

const detail = ref<RfqApi.Rfq>();
const insightDrawer = ref<{ open: (kind: string, id: number) => void }>();
const comparison = ref<RfqApi.QuoteComparison>();
const loading = ref(false);
const acting = ref(false);
const supplierMap = ref<Map<number, string>>(new Map());
const activeTab = ref('items');
const scenarioPriceWeight = ref(70);

const [SelectQuote, selectQuoteApi] = useVbenModal({
  connectedComponent: SelectQuoteModal,
  destroyOnClose: true,
});

const [Quote, quoteApi] = useVbenModal({
  connectedComponent: QuoteModal,
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
  const rfq = detail.value;
  if (!rfq?.id) {
    return;
  }
  acting.value = true;
  try {
    const proposal = await createActionProposalApi('rfq.send', { rfq_id: rfq.id }, makeIdempotencyKey());
    if (!canConfirmActionProposal(proposal, proposal.preview_version, false)) {
      message.warning(proposal.blockers.join('；') || '当前询价单不能发送，请检查后重试。');
      return;
    }
    Modal.confirm({
      title: '检查并发送询价单',
      content: `确认将询价单 ${rfq.rfq_no} 发送给已邀请供应商？发送后供应商即可报价，询价单不可再编辑。`,
      okText: '确认发送',
      onOk: async () => {
        await confirmActionProposalApi(proposal.confirmation_id, proposal.preview_version);
        message.success('询价单已发送');
        await reload();
        emit('success');
      },
    });
  } catch {
    // 请求层已统一弹出后端返回的中文错误；不吞掉异常会导致未捕获的 Promise 拒绝。
  } finally {
    acting.value = false;
  }
}

function makeIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
  } catch {
    // 同 onSend：错误提示由请求层负责，这里保持按钮可用以便重试。
  } finally {
    acting.value = false;
  }
}

function onQuote() {
  if (!detail.value?.id) {
    return;
  }
  quoteApi
    .setData({ id: detail.value.id, rfqNo: detail.value.rfq_no })
    .open();
}

async function onQuoteSuccess() {
  await reload();
  emit('success');
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
  } catch {
    // 同 onSend：错误提示由请求层负责，这里保持按钮可用以便重试。
  } finally {
    acting.value = false;
  }
}

const canSend = computed(
  () =>
    detail.value?.status === 'DRAFT' &&
    hasAccessByCodes(['procurement.rfqs.write']),
);
/** 后端只在 SENT / RESPONDING 状态接受报价 */
const canQuote = computed(() =>
  ['RESPONDING', 'SENT'].includes(detail.value?.status ?? '') &&
  hasAccessByCodes(['procurement.rfqs.quote']),
);
const canCompare = computed(
  () =>
    (detail.value?.quotes?.length ?? 0) > 0 &&
    detail.value?.status !== 'CLOSED' &&
    hasAccessByCodes(['procurement.rfqs.compare']),
);
const canCreateOrder = computed(
  () =>
    !!comparison.value?.selected_quote_id &&
    comparison.value?.status === 'CONFIRMED' &&
    hasAccessByCodes(['procurement.orders.write']),
);

const itemColumns = [
  { key: 'line_no', dataIndex: 'line_no', title: '行号', width: 70 },
  { key: 'requested_name', dataIndex: 'requested_name', title: '物料', minWidth: 160 },
  { key: 'specification', dataIndex: 'specification', title: '规格', width: 140 },
  { key: 'quantity', dataIndex: 'quantity', title: '数量', width: 110, align: 'right' as const },
  { key: 'required_delivery_date', dataIndex: 'required_delivery_date', title: '要求到货', width: 120 },
];

const quoteColumns = [
  { key: 'quote_no', dataIndex: 'quote_no', title: '报价单号', minWidth: 170 },
  { key: 'supplier_id', dataIndex: 'supplier_id', title: '供应商', minWidth: 160 },
  { key: 'quote_version', dataIndex: 'quote_version', title: '版本', width: 70 },
  { key: 'quote_date', dataIndex: 'quote_date', title: '报价日期', width: 120 },
  { key: 'valid_until', dataIndex: 'valid_until', title: '有效期至', width: 120 },
  { key: 'status', dataIndex: 'status', title: '状态', width: 100 },
];

const comparisonColumns = [
  { key: 'supplier_id', dataIndex: 'supplier_id', title: '供应商', minWidth: 160 },
  {
    key: 'quoted_unit_price',
    dataIndex: 'quoted_unit_price',
    title: '单价',
    width: 140,
    align: 'right' as const,
  },
  { key: 'total_amount', dataIndex: 'total_amount', title: '金额', width: 140, align: 'right' as const },
  { key: 'lead_days', dataIndex: 'lead_days', title: '交期(天)', width: 100 },
  { key: 'moq_quantity', dataIndex: 'moq_quantity', title: '最小起订量', width: 120 },
  { key: 'payment_terms', dataIndex: 'payment_terms', title: '付款条件', width: 140 },
  { key: 'rank_no', dataIndex: 'rank_no', title: '排名', width: 90 },
  { key: 'selection_flag', dataIndex: 'selection_flag', title: '中选', width: 90 },
  { key: '__action', dataIndex: '__action', title: '操作', width: 120 },
];

/** 用当前比价快照按价格与交期权重生成临时情景排序。 */
const scenarioCurrencyConflict = computed(() => {
  const currencies = new Set(
    (detail.value?.quotes ?? [])
      .filter((quote) => quote.status === 'SUBMITTED')
      .map((quote) => quote.currency_code),
  );
  return currencies.size > 1;
});

const scenarioRanking = computed(() => {
  if (scenarioCurrencyConflict.value) return [];
  const rows = comparison.value?.items ?? [];
  const groups = new Map<number, RfqApi.ComparisonItem[]>();
  for (const row of rows) {
    const group = groups.get(row.rfq_item_id) ?? [];
    group.push(row);
    groups.set(row.rfq_item_id, group);
  }
  const totalWeight = Math.max(0, Math.min(100, Number(scenarioPriceWeight.value) || 0));
  const priceWeight = totalWeight / 100;
  const leadWeight = 1 - priceWeight;
  const scores = new Map<number, { count: number; total: number }>();
  for (const group of groups.values()) {
    const prices = group.map((row) => Number(row.quoted_unit_price)).filter(Number.isFinite);
    const leads = group.map((row) => row.lead_days).filter((value): value is number => value != null);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const minLead = leads.length ? Math.min(...leads) : undefined;
    const maxLead = leads.length ? Math.max(...leads) : undefined;
    for (const row of group) {
      const price = Number(row.quoted_unit_price);
      const priceScore = maxPrice === minPrice ? 100 : ((maxPrice - price) / (maxPrice - minPrice)) * 100;
      const leadScore = row.lead_days == null || minLead == null || maxLead == null
        ? undefined
        : maxLead === minLead ? 100 : ((maxLead - row.lead_days) / (maxLead - minLead)) * 100;
      const weight = leadScore == null ? 1 : priceWeight + leadWeight;
      const score = leadScore == null
        ? priceScore
        : priceScore * priceWeight + leadScore * leadWeight;
      const current = scores.get(row.supplier_id) ?? { count: 0, total: 0 };
      current.count += 1;
      current.total += score / weight;
      scores.set(row.supplier_id, current);
    }
  }
  return [...scores.entries()]
    .map(([supplier_id, value]) => ({
      supplier_id,
      score: value.total / value.count,
      count: value.count,
    }))
    .sort((left, right) => right.score - left.score);
});

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="`询价单 ${detail?.rfq_no ?? ''}`" class="w-[1100px] max-w-[100vw]">
    <BusinessInsightDrawer ref="insightDrawer" />
    <SelectQuote @success="onSelectSuccess" />
    <Quote @success="onQuoteSuccess" />
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
          <Button
            v-if="detail.id && hasAccessByCodes(['procurement.orders.read']) && hasAccessByCodes(['ai.workspace.read'])"
            @click="insightDrawer?.open('supplier-change', detail.id)"
          >
            核对供应商变更
          </Button>
          <Button v-if="canSend" :loading="acting" type="primary" @click="onSend">
            发送询价单
          </Button>
          <Button v-if="canQuote" type="primary" @click="onQuote">
            录入报价
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
                  {{ formatDate(record.required_delivery_date) }}
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
                <template v-else-if="column.key === 'quote_date' || column.key === 'valid_until'">
                  {{ formatDate(record[column.key]) }}
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
              <div class="rounded-lg border p-3">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div class="font-medium">比价情景试算</div>
                    <div class="text-xs text-muted-foreground">只在本页临时计算，不改写正式比价结果；分数按每个询价明细的候选范围归一化。</div>
                  </div>
                  <div class="flex items-center gap-2 text-sm">
                    <span>价格 {{ scenarioPriceWeight }}%</span>
                    <InputNumber v-model:value="scenarioPriceWeight" :disabled="scenarioCurrencyConflict" :min="0" :max="100" :step="5" class="w-24" />
                    <span>交期 {{ 100 - scenarioPriceWeight }}%</span>
                  </div>
                </div>
                <Alert
                  v-if="scenarioCurrencyConflict"
                  class="mt-3"
                  show-icon
                  type="warning"
                  message="当前询价包含多种币种，暂不进行跨币种试算。"
                />
                <Empty
                  v-else-if="scenarioRanking.length === 0"
                  class="mt-3"
                  description="暂无可试算的结构化报价"
                />
                <Table
                  v-else
                  class="mt-3"
                  :columns="[
                    { key: 'rank', title: '情景排名', width: 100 },
                    { key: 'supplier_id', title: '供应商' },
                    { key: 'score', title: '试算分', width: 120, align: 'right' },
                    { key: 'count', title: '参与报价行', width: 120, align: 'right' },
                  ]"
                  :data-source="scenarioRanking"
                  :pagination="false"
                  row-key="supplier_id"
                  size="small"
                >
                  <template #bodyCell="{ column, record, index }">
                    <template v-if="column.key === 'rank'">第 {{ index + 1 }} 名</template>
                    <template v-else-if="column.key === 'supplier_id'">{{ supplierName(record.supplier_id) }}</template>
                    <template v-else-if="column.key === 'score'">{{ record.score.toFixed(1) }}</template>
                    <template v-else-if="column.key === 'count'">{{ record.count }}</template>
                  </template>
                </Table>
                <div class="mt-2 text-xs text-muted-foreground">当前缺少可比的历史履约与验收样本，因此本次只按报价价格和交期试算。</div>
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
                      v-if="comparison?.status !== 'CONFIRMED' && hasAccessByCodes(['procurement.rfqs.award'])"
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
