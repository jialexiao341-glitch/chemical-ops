<script lang="ts" setup>
import type { ProductApi, SupplierPortalApi } from '#/api';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { ArrowLeft, IconifyIcon } from '@vben/icons';

import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  message,
  Select,
  Spin,
  Tag,
} from 'antdv-next';

import {
  getSupplierRfqApi,
  getUnitListApi,
  submitSupplierQuoteApi,
} from '#/api';
import { RFQ_STATUS_DICT } from '#/constants/dictionary';
import { formatDate, formatDateTime, formatQuantity } from '#/utils/format';

defineOptions({ name: 'SupplierRfqDetail' });

interface QuoteLineForm {
  rfq_item_id: number;
  supplier_model: string;
  quoted_quantity: null | number;
  unit_id: number;
  unit_price: null | number;
  tax_rate: null | number;
  moq_quantity: null | number;
  moq_unit_id: null | number;
  lead_days: null | number;
  payment_terms: string;
}

const route = useRoute();
const router = useRouter();
const { hasAccessByCodes } = useAccess();
const rfq = ref<SupplierPortalApi.RfqDetail>();
const units = ref<ProductApi.Unit[]>([]);
const quoteLines = ref<QuoteLineForm[]>([]);
const quoteDate = ref('');
const validUntil = ref('');
const currencyCode = ref('CNY');
const quoteNote = ref('');
const loading = ref(false);
const submitting = ref(false);

const canQuote = computed(() => hasAccessByCodes(['supplier.portal.rfq.quote']));
const isOpen = computed(() => {
  if (!rfq.value || !['SENT', 'RESPONDING'].includes(rfq.value.status)) {
    return false;
  }
  return !rfq.value.quote_deadline || new Date(rfq.value.quote_deadline).getTime() > Date.now();
});
const canEditQuote = computed(() => canQuote.value && isOpen.value);
const canSubmitQuote = computed(
  () =>
    canEditQuote.value &&
    quoteLines.value.length > 0 &&
    quoteLines.value.every(
      (line) =>
        line.quoted_quantity !== null &&
        line.quoted_quantity > 0 &&
        line.unit_id > 0 &&
        line.unit_price !== null &&
        line.unit_price >= 0,
    ),
);

const unitOptions = computed(() =>
  units.value
    .filter((unit) => unit.status === 'ACTIVE')
    .map((unit) => ({ label: unit.unit_name, value: unit.id })),
);
const unitName = (unitId: number) =>
  units.value.find((unit) => unit.id === unitId)?.unit_name ?? `单位 #${unitId}`;

function localDate() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function initializeQuoteForm(detail: SupplierPortalApi.RfqDetail) {
  const latest = detail.latest_quote;
  const previousItems = new Map(
    (latest?.items ?? []).map((item) => [item.rfq_item_id, item]),
  );
  quoteLines.value = detail.items.map((item) => {
    const previous = previousItems.get(item.id);
    return {
      rfq_item_id: item.id,
      supplier_model: previous?.supplier_model ?? '',
      quoted_quantity: Number(previous?.quoted_quantity ?? item.quantity),
      unit_id: previous?.unit_id ?? item.unit_id,
      unit_price: previous ? Number(previous.unit_price) : null,
      tax_rate: previous?.tax_rate ? Number(previous.tax_rate) : null,
      moq_quantity: previous?.moq_quantity ? Number(previous.moq_quantity) : null,
      moq_unit_id: previous?.moq_unit_id ?? item.unit_id,
      lead_days: previous?.lead_days ?? null,
      payment_terms: previous?.payment_terms ?? '',
    };
  });
  quoteDate.value = latest?.quote_date ?? localDate();
  validUntil.value = latest?.valid_until ?? '';
  currencyCode.value = latest?.currency_code ?? 'CNY';
  quoteNote.value = latest?.note ?? '';
}

async function load() {
  const rfqId = Number(route.params.id);
  if (!Number.isInteger(rfqId) || rfqId <= 0) {
    return;
  }
  loading.value = true;
  try {
    const [detail, unitRows] = await Promise.all([
      getSupplierRfqApi(rfqId),
      getUnitListApi(),
    ]);
    rfq.value = detail;
    units.value = unitRows;
    initializeQuoteForm(detail);
  } finally {
    loading.value = false;
  }
}

async function submitQuote() {
  if (!rfq.value || !canSubmitQuote.value) {
    return;
  }
  submitting.value = true;
  try {
    const updated = await submitSupplierQuoteApi(rfq.value.id, {
      currency_code: currencyCode.value,
      items: quoteLines.value.map((line) => ({
        rfq_item_id: line.rfq_item_id,
        quoted_quantity: String(line.quoted_quantity),
        unit_id: line.unit_id,
        unit_price: String(line.unit_price),
        supplier_model: line.supplier_model || undefined,
        tax_rate: line.tax_rate ?? undefined,
        moq_quantity: line.moq_quantity ?? undefined,
        moq_unit_id: line.moq_quantity ? (line.moq_unit_id ?? undefined) : undefined,
        lead_days: line.lead_days ?? undefined,
        payment_terms: line.payment_terms || undefined,
      })),
      quote_date: quoteDate.value || undefined,
      valid_until: validUntil.value || undefined,
      note: quoteNote.value || undefined,
    });
    rfq.value = updated;
    initializeQuoteForm(updated);
    message.success(`报价已提交 · 第 ${updated.latest_quote?.quote_version ?? 1} 版`);
  } finally {
    submitting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <Page auto-content-height>
    <Spin :spinning="loading">
      <div v-if="rfq" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <Button class="!px-2" @click="router.back()">
              <ArrowLeft class="mr-1 size-4" />返回询价列表
            </Button>
            <span class="hidden h-6 w-px bg-border sm:block" />
            <h1 class="m-0 text-lg font-semibold leading-7">{{ rfq.rfq_no }}</h1>
          </div>
          <Tag :color="RFQ_STATUS_DICT.color(rfq.status)" class="m-0">
            {{ RFQ_STATUS_DICT.label(rfq.status) }}
          </Tag>
        </div>

        <Card class="rfq-summary">
          <div class="grid gap-5 md:grid-cols-[minmax(0,1fr)_260px]">
            <div>
              <div class="mb-3 flex items-center gap-2 text-sm font-semibold">
                <IconifyIcon class="size-4 text-primary" icon="lucide:file-text" />询价要求
              </div>
              <div class="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <div>
                  <div class="summary-label">报价截止</div>
                  <div class="summary-value flex items-center gap-2" :class="{ 'text-destructive': !isOpen }">
                    <IconifyIcon class="size-4" icon="lucide:clock-3" />
                    {{ formatDateTime(rfq.quote_deadline) }}
                  </div>
                </div>
                <div>
                  <div class="summary-label">期望交期</div>
                  <div class="summary-value">{{ formatDate(rfq.requested_delivery_date) }}</div>
                </div>
                <div class="sm:col-span-2">
                  <div class="summary-label">交付要求</div>
                  <div class="summary-value whitespace-pre-wrap">{{ rfq.delivery_requirements || '未提供额外交付要求' }}</div>
                </div>
              </div>
            </div>
            <aside class="quote-status-box">
              <div class="summary-label">我的响应</div>
              <div class="mt-1 text-lg font-semibold">
                {{ rfq.latest_quote ? `已提交 · 第 ${rfq.latest_quote.quote_version} 版` : '等待报价' }}
              </div>
              <p class="mb-0 mt-2 text-sm leading-6 text-muted-foreground">
                {{ isOpen ? '询价截止前可再次提交，系统会保留每个报价版本。' : '当前询价已关闭或超过截止时间，不能提交新报价。' }}
              </p>
            </aside>
          </div>
        </Card>

        <Card class="rfq-items-card">
          <template #title>
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span>物料与报价</span>
              <span class="text-sm font-normal text-muted-foreground">{{ rfq.items.length }} 项 · {{ currencyCode }}</span>
            </div>
          </template>
          <Empty v-if="rfq.items.length === 0" description="该询价没有物料明细" />
          <div v-else class="space-y-5">
            <section
              v-for="(item, index) in rfq.items"
              :key="item.id"
              class="quote-line"
            >
              <div class="quote-line-heading">
                <div class="flex min-w-0 items-start gap-3">
                  <span class="quote-line-number">{{ String(index + 1).padStart(2, '0') }}</span>
                  <div class="min-w-0">
                    <h2 class="m-0 truncate text-base font-semibold" :title="item.requested_name">
                      {{ item.requested_name }}
                    </h2>
                    <div class="mt-1 text-sm text-muted-foreground">
                      {{ item.specification || '未注明规格' }}
                    </div>
                  </div>
                </div>
                <div class="text-right text-sm">
                  <div class="text-muted-foreground">需求数量</div>
                  <strong>{{ formatQuantity(item.quantity) }} {{ unitName(item.unit_id) }}</strong>
                </div>
              </div>
              <div v-if="item.technical_requirements" class="technical-requirements">
                <span class="font-medium">技术要求</span>
                <span class="whitespace-pre-wrap">{{ item.technical_requirements }}</span>
              </div>

              <div class="quote-fields" :class="{ 'quote-fields--readonly': !canEditQuote }">
                <label class="field-block">
                  <span>供应商型号</span>
                  <Input v-model:value="quoteLines[index]!.supplier_model" :disabled="!canEditQuote" :maxlength="128" placeholder="选填" />
                </label>
                <label class="field-block">
                  <span>报价数量</span>
                  <InputNumber v-model:value="quoteLines[index]!.quoted_quantity" :disabled="!canEditQuote" :min="0.000001" :precision="6" class="w-full" />
                </label>
                <label class="field-block">
                  <span>报价单位</span>
                  <Select v-model:value="quoteLines[index]!.unit_id" :disabled="!canEditQuote" :options="unitOptions" class="w-full" />
                </label>
                <label class="field-block">
                  <span>未税单价</span>
                  <InputNumber v-model:value="quoteLines[index]!.unit_price" :disabled="!canEditQuote" :min="0" :precision="6" class="w-full" />
                </label>
                <label class="field-block">
                  <span>税率（%）</span>
                  <InputNumber v-model:value="quoteLines[index]!.tax_rate" :disabled="!canEditQuote" :min="0" :max="100" :precision="2" class="w-full" placeholder="选填" />
                </label>
                <label class="field-block">
                  <span>交货周期（天）</span>
                  <InputNumber v-model:value="quoteLines[index]!.lead_days" :disabled="!canEditQuote" :min="0" :precision="0" class="w-full" placeholder="选填" />
                </label>
                <label class="field-block">
                  <span>最小起订量</span>
                  <InputNumber v-model:value="quoteLines[index]!.moq_quantity" :disabled="!canEditQuote" :min="0.000001" :precision="6" class="w-full" placeholder="选填" />
                </label>
                <label class="field-block">
                  <span>起订量单位</span>
                  <Select v-model:value="quoteLines[index]!.moq_unit_id" :disabled="!canEditQuote" :options="unitOptions" allow-clear class="w-full" placeholder="同报价单位" />
                </label>
                <label class="field-block field-block--wide">
                  <span>付款条件</span>
                  <Input v-model:value="quoteLines[index]!.payment_terms" :disabled="!canEditQuote" :maxlength="255" placeholder="选填" />
                </label>
              </div>
            </section>
          </div>
        </Card>

        <Card v-if="canEditQuote" class="quote-submit-card">
          <div class="grid gap-4 md:grid-cols-[160px_180px_150px_minmax(0,1fr)]">
            <label class="field-block">
              <span>报价日期</span>
              <Input v-model:value="quoteDate" type="date" />
            </label>
            <label class="field-block">
              <span>报价有效期</span>
              <Input v-model:value="validUntil" type="date" />
            </label>
            <label class="field-block">
              <span>报价币种</span>
              <Select
                v-model:value="currencyCode"
                :options="[
                  { label: '人民币 CNY', value: 'CNY' },
                  { label: '美元 USD', value: 'USD' },
                  { label: '欧元 EUR', value: 'EUR' },
                  { label: '日元 JPY', value: 'JPY' },
                ]"
                class="w-full"
              />
            </label>
            <label class="field-block">
              <span>报价备注</span>
              <Input v-model:value="quoteNote" :maxlength="1000" placeholder="选填，填写整体商务说明" />
            </label>
          </div>
          <Alert
            class="mt-4"
            show-icon
            type="info"
            :message="rfq.latest_quote ? `再次提交会保存为第 ${rfq.latest_quote.quote_version + 1} 版，不覆盖已提交记录。` : '提交后采购方即可查看本次报价。所有物料均需填写报价数量和未税单价。'"
          />
          <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
            <span class="text-sm leading-6 text-muted-foreground">
              提交后记录当前版本；截止时间前仍可提交修订版本。
            </span>
            <Button type="primary" :loading="submitting" :disabled="!canSubmitQuote" @click="submitQuote">
              <IconifyIcon class="mr-2 size-4" icon="lucide:send" />
              {{ rfq.latest_quote ? '提交报价修订' : '提交报价' }}
            </Button>
          </div>
        </Card>

        <Alert
          v-else-if="!canQuote"
          show-icon
          type="warning"
          message="当前账号只有询价读取权限，不能提交报价。"
        />
        <Alert
          v-else-if="!isOpen"
          show-icon
          type="warning"
          message="询价已关闭或已过报价截止时间，当前页面仅供查看。"
        />
      </div>
      <Empty v-else-if="!loading" description="询价不存在，或当前供应商账号未受邀参与" />
    </Spin>
  </Page>
</template>

<style scoped>
.rfq-summary,
.rfq-items-card,
.quote-submit-card {
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  box-shadow: none;
}

.summary-label {
  color: hsl(var(--muted-foreground));
  font-size: 14px;
  line-height: 1.5;
}

.summary-value {
  margin-top: 4px;
  color: hsl(var(--foreground));
  font-size: 14px;
  line-height: 1.6;
}

.quote-status-box {
  padding: 16px 18px;
  border: 1px solid hsl(var(--primary) / 18%);
  border-radius: 8px;
  background: hsl(var(--primary) / 4%);
}

.quote-line {
  padding: 18px 0 22px;
  border-bottom: 1px solid hsl(var(--border));
}

.quote-line:first-child {
  padding-top: 0;
}

.quote-line:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.quote-line-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.quote-line-number {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border-radius: 7px;
  background: hsl(var(--primary) / 9%);
  color: hsl(var(--primary));
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.technical-requirements {
  display: flex;
  gap: 8px;
  margin: 0 0 16px 47px;
  padding: 10px 12px;
  border-left: 2px solid hsl(var(--primary) / 40%);
  background: hsl(var(--muted) / 35%);
  color: hsl(var(--muted-foreground));
  font-size: 14px;
  line-height: 1.6;
}

.quote-fields {
  display: grid;
  gap: 14px 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.field-block {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
  color: hsl(var(--muted-foreground));
  font-size: 14px;
}

.field-block--wide {
  grid-column: span 2;
}

.quote-fields--readonly :deep(.ant-input),
.quote-fields--readonly :deep(.ant-input-number),
.quote-fields--readonly :deep(.ant-select-selector) {
  background-color: hsl(var(--muted) / 35%);
}

@media (max-width: 900px) {
  .quote-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .quote-line-heading {
    align-items: flex-start;
  }

  .quote-fields {
    grid-template-columns: 1fr;
  }

  .field-block--wide {
    grid-column: span 1;
  }

  .technical-requirements {
    flex-direction: column;
    margin-left: 0;
  }
}
</style>
