<script lang="ts" setup>
import type { DeliveryApi } from '#/api';

import { ref } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Descriptions, DescriptionsItem, Empty, Spin, Table, Tag } from 'antdv-next';

import { getDeliveryApi } from '#/api';
import { formatDate, formatDateTime } from '#/utils/format';

const detail = ref<DeliveryApi.Delivery>();
const loading = ref(false);

const [Drawer, drawerApi] = useVbenDrawer<null | DeliveryApi.Delivery>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) return;
    const id = drawerApi.getData()?.id;
    detail.value = undefined;
    if (!id) return;
    loading.value = true;
    try {
      detail.value = await getDeliveryApi(id);
    } finally {
      loading.value = false;
    }
  },
});

const itemColumns = [
  { key: 'id', title: '明细 ID', width: 90 },
  { key: 'po_item_id', title: '订单明细 ID', width: 110 },
  { key: 'planned_quantity', title: '计划数量', width: 120, align: 'right' as const },
  { key: 'actual_quantity', title: '实收数量', width: 120, align: 'right' as const },
  { key: 'short_quantity', title: '短交数量', width: 120, align: 'right' as const },
  { key: 'batch_no', title: '批次号', minWidth: 140 },
  { key: 'document_complete', title: '单证齐全', width: 100 },
];
</script>

<template>
  <Drawer :title="`到货单 ${detail?.delivery_no ?? ''}`" class="w-[900px]">
    <Spin :spinning="loading">
      <Empty v-if="!detail && !loading" description="未找到该到货单或当前账号无权查看" />
      <div v-else-if="detail" class="space-y-4">
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="到货单号">{{ detail.delivery_no }}</DescriptionsItem>
          <DescriptionsItem label="状态"><Tag>{{ detail.status }}</Tag></DescriptionsItem>
          <DescriptionsItem label="采购订单 ID">{{ detail.po_id }}</DescriptionsItem>
          <DescriptionsItem label="供应商 ID">{{ detail.supplier_id ?? '—' }}</DescriptionsItem>
          <DescriptionsItem label="预计到货">{{ formatDate(detail.expected_arrival_date) }}</DescriptionsItem>
          <DescriptionsItem label="实际到货">{{ formatDate(detail.actual_arrival_date) }}</DescriptionsItem>
          <DescriptionsItem label="物流公司">{{ detail.logistics_company || '—' }}</DescriptionsItem>
          <DescriptionsItem label="运单号">{{ detail.tracking_no || '—' }}</DescriptionsItem>
          <DescriptionsItem label="收货时间">{{ formatDateTime(detail.received_at) }}</DescriptionsItem>
          <DescriptionsItem label="备注">{{ detail.note || '—' }}</DescriptionsItem>
        </Descriptions>
        <div class="font-medium">到货明细（{{ detail.items?.length ?? 0 }}）</div>
        <Table
          :columns="itemColumns"
          :data-source="detail.items ?? []"
          :pagination="false"
          row-key="id"
          size="small"
          :scroll="{ x: 780 }"
        />
      </div>
    </Spin>
  </Drawer>
</template>
