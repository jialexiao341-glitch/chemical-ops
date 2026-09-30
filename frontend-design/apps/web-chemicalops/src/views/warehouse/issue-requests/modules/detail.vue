<script lang="ts" setup>
import type { IssueRequestApi } from '#/api';

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

import { getIssueApi } from '#/api';
import { APPROVAL_FLOW_STATUS_DICT, LINE_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime, formatQuantity } from '#/utils/format';
import {
  getProductNameMap,
  getUnitNameMap,
  getWarehouseNameMap,
} from '#/utils/lookup';

const detail = ref<IssueRequestApi.IssueRequest>();
const loading = ref(false);
const productName = ref<(id?: null | number) => string>(() => '-');
const warehouseName = ref<(id?: null | number) => string>(() => '-');
const unitName = ref<(id?: null | number) => string>(() => '-');

const [Drawer, drawerApi] = useVbenDrawer<null | IssueRequestApi.IssueRequest>(
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
        const [issue, products, warehouses, units] = await Promise.all([
          getIssueApi(data.id),
          getProductNameMap(),
          getWarehouseNameMap(),
          getUnitNameMap(),
        ]);
        detail.value = issue;
        productName.value = (id) =>
          !id ? '-' : (products.get(id) ?? `#${id}`);
        warehouseName.value = (id) =>
          !id ? '-' : (warehouses.get(id) ?? `#${id}`);
        unitName.value = (id) => (!id ? '-' : (units.get(id) ?? `#${id}`));
      } finally {
        loading.value = false;
      }
    },
  },
);

const itemColumns = [
  { key: 'line_no', title: '行号', width: 70 },
  { key: 'product_id', title: '产品', minWidth: 180 },
  { key: 'warehouse_id', title: '仓库', width: 120 },
  { key: 'batch_id', title: '批次', width: 90 },
  { key: 'requested_quantity', title: '申请数量', width: 110, align: 'right' as const },
  { key: 'issued_quantity', title: '已发数量', width: 110, align: 'right' as const },
  { key: 'unit_id', title: '单位', width: 80 },
  { key: 'status', title: '状态', width: 100 },
];

const titleText = computed(
  () => `领用申请 · ${detail.value?.issue_no ?? ''}`,
);

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="titleText" class="w-[900px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该申请" />
      <div v-else-if="detail" class="space-y-5">
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="领用单号">
            {{ detail.issue_no }}
          </DescriptionsItem>
          <DescriptionsItem label="状态">
            <Tag :color="APPROVAL_FLOW_STATUS_DICT.color(detail.status)">
              {{ APPROVAL_FLOW_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="部门">
            {{ detail.department_id ? `#${detail.department_id}` : '-' }}
          </DescriptionsItem>
          <DescriptionsItem label="申请人">
            #{{ detail.applicant_id }}
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
          <div class="mb-3 font-medium">领用明细</div>
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
              <template v-else-if="column.key === 'warehouse_id'">
                {{ warehouseName(record.warehouse_id) }}
              </template>
              <template v-else-if="column.key === 'requested_quantity'">
                {{ formatQuantity(record.requested_quantity) }}
              </template>
              <template v-else-if="column.key === 'issued_quantity'">
                {{ formatQuantity(record.issued_quantity) }}
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
