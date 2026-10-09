<script lang="ts" setup>
import type { StocktakeApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';

import {
  Button,
  Descriptions,
  DescriptionsItem,
  Empty,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import { getStocktakeApi } from '#/api';
import {
  APPROVAL_FLOW_STATUS_DICT,
  LINE_STATUS_DICT,
} from '#/constants/dictionary';
import { formatDateTime, formatQuantity } from '#/utils/format';
import {
  getProductNameMap,
  getUnitNameMap,
  getWarehouseNameMap,
} from '#/utils/lookup';
import BusinessInsightDrawer from '#/views/ai/workspace/modules/business-insight-drawer.vue';

const detail = ref<StocktakeApi.StocktakeRequest>();
const { hasAccessByCodes } = useAccess();
const insightDrawer = ref<{ open: (kind: string, id: number) => void }>();
const loading = ref(false);
const productName = ref<(id?: null | number) => string>(() => '-');
const unitName = ref<(id?: null | number) => string>(() => '-');
const warehouseName = ref<(id?: null | number) => string>(() => '-');

const [Drawer, drawerApi] = useVbenDrawer<null | StocktakeApi.StocktakeRequest>(
  {
    footer: false,
    async onOpenChange(isOpen) {
      if (!isOpen) {
        return;
      }
      const data = drawerApi.getData();
      detail.value = undefined;
      if (!data?.id) {
        return;
      }
      loading.value = true;
      try {
        const [stocktake, products, units, warehouses] = await Promise.all([
          getStocktakeApi(data.id),
          getProductNameMap(),
          getUnitNameMap(),
          getWarehouseNameMap(),
        ]);
        detail.value = stocktake;
        productName.value = (id) =>
          !id ? '-' : (products.get(id) ?? `#${id}`);
        unitName.value = (id) => (!id ? '-' : (units.get(id) ?? `#${id}`));
        warehouseName.value = (id) =>
          !id ? '-' : (warehouses.get(id) ?? `#${id}`);
      } finally {
        loading.value = false;
      }
    },
  },
);

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'product_id', title: '产品', minWidth: 160 },
  { key: 'book_quantity', title: '账面数量', width: 110, align: 'right' as const },
  { key: 'counted_quantity', title: '实盘数量', width: 110, align: 'right' as const },
  {
    key: 'difference_quantity',
    title: '差异数量',
    width: 110,
    align: 'right' as const,
  },
  { key: 'unit_id', title: '单位', width: 80 },
  { key: 'status', title: '状态', width: 100 },
];

const titleText = computed(
  () => `盘点申请 · ${detail.value?.stocktake_no ?? ''}`,
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="titleText" class="w-[900px] max-w-[100vw]">
    <BusinessInsightDrawer ref="insightDrawer" />
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该申请" />
      <div v-else-if="detail" class="space-y-5">
        <Button v-if="hasAccessByCodes(['ai.workspace.read'])" @click="insightDrawer?.open('stocktake-explain', detail.id)">
          分析盘点差异
        </Button>
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="盘点单号">
            {{ detail.stocktake_no }}
          </DescriptionsItem>
          <DescriptionsItem label="状态">
            <Tag :color="APPROVAL_FLOW_STATUS_DICT.color(detail.status)">
              {{ APPROVAL_FLOW_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="仓库">
            {{ warehouseName(detail.warehouse_id) }}
          </DescriptionsItem>
          <DescriptionsItem label="库位">
            {{ detail.location_id ? `#${detail.location_id}` : '整仓' }}
          </DescriptionsItem>
          <DescriptionsItem :span="2" label="用途">
            {{ detail.purpose }}
          </DescriptionsItem>
          <DescriptionsItem v-if="detail.reject_reason" :span="2" label="驳回原因">
            {{ detail.reject_reason }}
          </DescriptionsItem>
          <DescriptionsItem label="审批时间">
            {{ formatDateTime(detail.approved_at) }}
          </DescriptionsItem>
          <DescriptionsItem label="完成时间">
            {{ formatDateTime(detail.completed_at) }}
          </DescriptionsItem>
        </Descriptions>

        <div>
          <div class="mb-3 font-medium">盘点明细（账面为创建时快照）</div>
          <Table
            :columns="itemColumns"
            :data-source="detail.items ?? []"
            :pagination="false"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'product_id'">
                {{ productName(record.product_id) }}
              </template>
              <template v-else-if="column.key === 'book_quantity'">
                {{ formatQuantity(record.book_quantity) }}
              </template>
              <template v-else-if="column.key === 'counted_quantity'">
                {{ formatQuantity(record.counted_quantity) }}
              </template>
              <template v-else-if="column.key === 'difference_quantity'">
                <span
                  :class="
                    Number(record.difference_quantity) < 0
                      ? 'text-red-600'
                      : Number(record.difference_quantity) > 0
                        ? 'text-emerald-600'
                        : ''
                  "
                >
                  {{ formatQuantity(record.difference_quantity) }}
                </span>
              </template>
              <template v-else-if="column.key === 'unit_id'">
                {{ unitName(record.unit_id) }}
              </template>
              <template v-else-if="column.key === 'status'">
                <Tag :color="LINE_STATUS_DICT.color(record.status)">
                  {{ LINE_STATUS_DICT.label(record.status) }}
                </Tag>
              </template>
            </template>
          </Table>
        </div>
      </div>
    </Spin>
  </Drawer>
</template>
