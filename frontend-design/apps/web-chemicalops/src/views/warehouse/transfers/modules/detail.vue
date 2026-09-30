<script lang="ts" setup>
import type { TransferRequestApi } from '#/api';

import { computed, ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import {
  Descriptions,
  DescriptionsItem,
  Empty,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import { getTransferApi } from '#/api';
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

const detail = ref<TransferRequestApi.TransferRequest>();
const loading = ref(false);
const productName = ref<(id?: null | number) => string>(() => '-');
const warehouseName = ref<(id?: null | number) => string>(() => '-');
const unitName = ref<(id?: null | number) => string>(() => '-');

const [Drawer, drawerApi] = useVbenDrawer<
  null | TransferRequestApi.TransferRequest
>({
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
      const [transfer, products, warehouses, units] = await Promise.all([
        getTransferApi(data.id),
        getProductNameMap(),
        getWarehouseNameMap(),
        getUnitNameMap(),
      ]);
      detail.value = transfer;
      productName.value = (id) => (!id ? '-' : (products.get(id) ?? `#${id}`));
      warehouseName.value = (id) =>
        !id ? '-' : (warehouses.get(id) ?? `#${id}`);
      unitName.value = (id) => (!id ? '-' : (units.get(id) ?? `#${id}`));
    } finally {
      loading.value = false;
    }
  },
});

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'product_id', title: '产品', minWidth: 160 },
  { key: 'source_warehouse_id', title: '源仓库', width: 110 },
  { key: 'target_warehouse_id', title: '目标仓库', width: 110 },
  {
    key: 'requested_quantity',
    title: '申请数量',
    width: 100,
    align: 'right' as const,
  },
  {
    key: 'transferred_quantity',
    title: '已调拨',
    width: 100,
    align: 'right' as const,
  },
  { key: 'unit_id', title: '单位', width: 80 },
  { key: 'status', title: '状态', width: 100 },
];

const titleText = computed(
  () => `调拨申请 · ${detail.value?.transfer_no ?? ''}`,
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="titleText" class="w-[920px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该申请" />
      <div v-else-if="detail" class="space-y-5">
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="调拨单号">
            {{ detail.transfer_no }}
          </DescriptionsItem>
          <DescriptionsItem label="状态">
            <Tag :color="APPROVAL_FLOW_STATUS_DICT.color(detail.status)">
              {{ APPROVAL_FLOW_STATUS_DICT.label(detail.status) }}
            </Tag>
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
          <div class="mb-3 font-medium">调拨明细</div>
          <Table
            :columns="itemColumns"
            :data-source="detail.items ?? []"
            :pagination="false"
            :scroll="{ x: 900 }"
            row-key="id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'product_id'">
                {{ productName(record.product_id) }}
              </template>
              <template v-else-if="column.key === 'source_warehouse_id'">
                {{ warehouseName(record.source_warehouse_id) }}
              </template>
              <template v-else-if="column.key === 'target_warehouse_id'">
                {{ warehouseName(record.target_warehouse_id) }}
              </template>
              <template v-else-if="column.key === 'requested_quantity'">
                {{ formatQuantity(record.requested_quantity) }}
              </template>
              <template v-else-if="column.key === 'transferred_quantity'">
                {{ formatQuantity(record.transferred_quantity) }}
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
