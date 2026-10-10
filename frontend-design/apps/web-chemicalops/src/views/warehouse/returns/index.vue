<script lang="ts" setup>
import type { InventoryReturn } from '#/api';
import type { VxeTableGridOptions } from '#/adapter/vxe-table';

import { ref } from 'vue';
import { useAccess } from '@vben/access';
import { useUserStore } from '@vben/stores';
import { Page } from '@vben/common-ui';
import { Alert, Button, Input, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { actInventoryReturnApi, getInventoryReturnsApi } from '#/api';
import { APPROVAL_FLOW_STATUS_DICT } from '#/constants/dictionary';
import { formatQuantity } from '#/utils/format';

defineOptions({ name: 'InventoryReturns' });
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const busy = ref(false);
const rejectRow = ref<InventoryReturn>();
const reason = ref('');
const rejectVisible = ref(false);

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: [{
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: APPROVAL_FLOW_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    }],
  },
  gridOptions: {
    columns: [
      { type: 'expand', width: 48, slots: { content: 'return-items' } },
      { field: 'return_no', title: '退货单号', width: 190 },
      { field: 'reason', title: '退货原因', minWidth: 320, align: 'left' },
      {
        field: 'status', title: '状态', width: 110,
        cellRender: { name: 'CellTag', options: APPROVAL_FLOW_STATUS_DICT.items },
      },
      { title: '操作', width: 220, fixed: 'right', slots: { default: 'actions' } },
    ],
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: ({ page }, formValues) => getInventoryReturnsApi({
          page: page.currentPage,
          page_size: page.pageSize,
          status: formValues.status,
        }),
      },
    },
    rowConfig: { keyField: 'id' },
    toolbarConfig: { custom: true, refresh: true, search: true, zoom: true },
  } as VxeTableGridOptions<InventoryReturn>,
});

async function act(row: InventoryReturn, action: 'approve' | 'cancel' | 'execute' | 'reject' | 'submit', note?: string) {
  if (busy.value) return;
  busy.value = true;
  try {
    await actInventoryReturnApi(row.id, action, note);
    message.success('操作成功');
    rejectVisible.value = false;
    await gridApi.query();
  } catch {
    // 错误由请求层显示，保持驳回原因。
  } finally {
    busy.value = false;
  }
}
function confirmAction(row: InventoryReturn, action: 'approve' | 'cancel' | 'execute' | 'submit') {
  Modal.confirm({ title: action === 'execute' ? '确认退货出库' : '确认操作', content: action === 'execute' ? `执行 ${row.return_no} 将扣减库存并记录退货成本，请确认实物已完成退货。` : `确认处理退货单 ${row.return_no}？`, onOk: () => act(row, action) });
}
function reject(row: InventoryReturn) { rejectRow.value = row; reason.value = ''; rejectVisible.value = true; }
function submitReject() {
  if (!reason.value.trim()) { message.warning('请填写驳回原因'); return; }
  if (rejectRow.value) void act(rejectRow.value, 'reject', reason.value.trim());
}
</script>

<template>
  <Page auto-content-height>
    <Grid table-title="供应商退货" table-title-help="从库存台账的“申请退货”创建草稿。展开退货单可查看产品、数量及原始到货和采购订单。">
      <template #actions="{ row }">
        <div class="flex items-center justify-center gap-1">
          <template v-if="hasAccessByCodes(['warehouse.inventory.return.write'])">
            <Button v-if="['DRAFT', 'REJECTED'].includes(row.status)" size="small" type="link" :disabled="busy" @click="confirmAction(row, 'submit')">提交审批</Button>
            <Button v-if="['DRAFT', 'REJECTED'].includes(row.status)" size="small" type="link" :disabled="busy" @click="confirmAction(row, 'cancel')">取消</Button>
            <Button v-if="row.status === 'APPROVED'" size="small" type="link" :disabled="busy" @click="confirmAction(row, 'execute')">执行出库</Button>
          </template>
          <template v-if="hasAccessByCodes(['warehouse.inventory.return.approve'])">
            <Button size="small" type="link" :disabled="busy || row.status !== 'SUBMITTED' || String(row.applicant_id) === String(userStore.userInfo?.userId)" :title="String(row.applicant_id) === String(userStore.userInfo?.userId) ? '不能审批本人经办的退货申请' : row.status !== 'SUBMITTED' ? '仅待审批申请可审批或驳回' : undefined" @click="confirmAction(row, 'approve')">审批通过</Button>
            <Button size="small" danger type="link" :disabled="busy || row.status !== 'SUBMITTED' || String(row.applicant_id) === String(userStore.userInfo?.userId)" :title="String(row.applicant_id) === String(userStore.userInfo?.userId) ? '不能审批本人经办的退货申请' : row.status !== 'SUBMITTED' ? '仅待审批申请可审批或驳回' : undefined" @click="reject(row)">驳回</Button>
          </template>
        </div>
      </template>
      <template #return-items="{ row }">
        <div class="space-y-2 p-4 text-sm">
          <Alert v-if="row.reject_reason" type="warning" :message="`驳回原因：${row.reject_reason}`" />
          <div v-for="item in row.items" :key="item.id" class="border-border border-b py-2">
            <div>{{ item.product_name || '产品名称未记录' }} · 申请 {{ formatQuantity(item.requested_quantity) }} / 已退 {{ formatQuantity(item.returned_quantity) }} {{ item.unit_name }}</div>
            <div class="text-muted-foreground">{{ item.source_po_no || '订单行来源待核查' }} · {{ item.source_delivery_no || '到货明细来源未记录' }}</div>
          </div>
        </div>
      </template>
    </Grid>
    <Modal v-model:open="rejectVisible" title="驳回退货申请" :confirm-loading="busy" @ok="submitReject">
      <Input.TextArea v-model:value="reason" :rows="3" :maxlength="1000" placeholder="填写驳回原因" />
    </Modal>
  </Page>
</template>
