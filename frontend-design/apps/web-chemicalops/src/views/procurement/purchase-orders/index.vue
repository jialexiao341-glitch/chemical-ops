<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { PurchaseOrderApi } from '#/api';

import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page, useVbenModal } from '@vben/common-ui';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  getPurchaseOrderListApi,
  placePurchaseOrderApi,
  submitPurchaseOrderApi,
} from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import ApproveModal from './modules/approve.vue';
import CancelModal from './modules/cancel.vue';

defineOptions({ name: 'PurchaseOrderList' });

const router = useRouter();

const [Approve, approveApi] = useVbenModal({
  connectedComponent: ApproveModal,
  destroyOnClose: true,
});

const [Cancel, cancelApi] = useVbenModal({
  connectedComponent: CancelModal,
  destroyOnClose: true,
});

const resolveSupplier = ref<(id?: null | number) => string>(() => '-');

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick, (id) => resolveSupplier.value(id)),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getPurchaseOrderListApi({
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
  } as VxeTableGridOptions<PurchaseOrderApi.PurchaseOrder>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<PurchaseOrderApi.PurchaseOrder>) {
  const payload = { id: row.id, poNo: row.po_no };
  switch (code) {
    case 'approve': {
      approveApi.setData({ ...payload, action: 'approve' }).open();
      break;
    }
    case 'cancel': {
      cancelApi.setData(payload).open();
      break;
    }
    case 'detail': {
      router.push({
        name: 'PurchaseOrderDetail',
        params: { id: row.id },
      });
      break;
    }
    case 'place': {
      onPlace(row);
      break;
    }
    case 'reject': {
      approveApi.setData({ ...payload, action: 'reject' }).open();
      break;
    }
    case 'submit': {
      onSubmit(row);
      break;
    }
  }
}

function onSubmit(row: PurchaseOrderApi.PurchaseOrder) {
  Modal.confirm({
    content: `提交后订单进入审批流程：${row.po_no}`,
    onOk: async () => {
      await submitPurchaseOrderApi(row.id);
      message.success('已提交审批');
      gridApi.query();
    },
    okText: '提交',
    title: '提交采购订单审批',
  });
}

/** 正式下单，后端会回写采购申请明细的已采购数量 */
function onPlace(row: PurchaseOrderApi.PurchaseOrder) {
  Modal.confirm({
    content: `正式下单后订单进入执行状态，并回写采购申请的已采购数量：${row.po_no}`,
    onOk: async () => {
      await placePurchaseOrderApi(row.id);
      message.success('已正式下单');
      gridApi.query();
    },
    okText: '确认下单',
    title: '正式下单',
  });
}

onMounted(async () => {
  const suppliers = await getSupplierNameMap();
  resolveSupplier.value = (id) => {
    if (!id) {
      return '-';
    }
    return suppliers.get(id) ?? `#${id}`;
  };
  gridApi.query();
});
</script>

<template>
  <Page auto-content-height>
    <Approve @success="gridApi.query()" />
    <Cancel @success="gridApi.query()" />
    <Grid table-title="采购订单">
      <template #toolbar-tools>
        <Button @click="gridApi.query()">刷新</Button>
      </template>
      <template #po_no="{ row }">
        <Button
          size="small"
          type="link"
          @click="
            router.push({ name: 'PurchaseOrderDetail', params: { id: row.id } })
          "
        >
          {{ row.po_no }}
        </Button>
      </template>
    </Grid>
  </Page>
</template>
