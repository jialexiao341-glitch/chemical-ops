<script lang="ts" setup>
import type { InventoryApi } from '#/api';

import { ref, watch } from 'vue';

import { useVbenDrawer } from '@vben/common-ui';

import { Empty, Spin, Table, Tag } from 'antdv-next';

import { getBalanceStatusLogsApi } from '#/api';
import { formatDateTime } from '#/utils/format';

const balanceId = ref<null | number>();
const loading = ref(false);
const logs = ref<InventoryApi.BalanceStatusLog[]>([]);

const [Drawer, drawerApi] = useVbenDrawer<null | number>({
  footer: false,
  onOpenChange(isOpen) {
    if (isOpen) {
      balanceId.value = drawerApi.getData();
    }
  },
});

const STATUS_LABEL: Record<string, string> = {
  AVAILABLE: '可用',
  FROZEN: '冻结',
};

/** 状态码转中文，未知状态原样展示 */
function statusLabel(value?: null | string) {
  if (!value) {
    return '-';
  }
  return STATUS_LABEL[value] ?? value;
}

watch(balanceId, async (id) => {
  if (!id) {
    logs.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await getBalanceStatusLogsApi(id, {
      page: 1,
      page_size: 100,
    });
    logs.value = res.items;
  } finally {
    loading.value = false;
  }
});

const columns = [
  { dataIndex: 'created_at', key: 'created_at', title: '时间', width: 170 },
  { dataIndex: 'before_status', key: 'before_status', title: '变更前', width: 100 },
  { dataIndex: 'after_status', key: 'after_status', title: '变更后', width: 100 },
  { dataIndex: 'reason', key: 'reason', title: '原因' },
];

defineExpose({ drawerApi });
</script>

<template>
  <Drawer :title="`库存批次 #${balanceId ?? ''} 状态变更记录`" class="w-[720px] max-w-[100vw]">
    <Spin :spinning="loading">
      <Empty v-if="logs.length === 0 && !loading" description="暂无变更记录" />
      <Table
        v-else
        :columns="columns"
        :data-source="logs"
        :pagination="false"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at'">
            {{ formatDateTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'before_status'">
            <Tag>{{ statusLabel(record.before_status) }}</Tag>
          </template>
          <template v-else-if="column.key === 'after_status'">
            <Tag
              :color="record.after_status === 'FROZEN' ? 'warning' : 'success'"
            >
              {{ statusLabel(record.after_status) }}
            </Tag>
          </template>
        </template>
      </Table>
    </Spin>
  </Drawer>
</template>
