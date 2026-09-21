<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { DeliveryApi } from '#/api';

import { onMounted, ref } from 'vue';

import { Page, useVbenModal } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { getDeliveryListApi } from '#/api';
import { getSupplierNameMap } from '#/utils/lookup';

import { useColumns, useGridFormSchema } from './data';
import CreateModal from './modules/create.vue';
import ReceiveModal from './modules/receive.vue';

defineOptions({ name: 'DeliveryList' });

const [Create, createApi] = useVbenModal({
  connectedComponent: CreateModal,
  destroyOnClose: true,
});

const [Receive, receiveApi] = useVbenModal({
  connectedComponent: ReceiveModal,
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
          return await getDeliveryListApi({
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
  } as VxeTableGridOptions<DeliveryApi.Delivery>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<DeliveryApi.Delivery>) {
  if (code === 'receive') {
    receiveApi.setData(row).open();
  }
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
    <Create @success="gridApi.query()" />
    <Receive @success="gridApi.query()" />
    <Grid table-title="到货与收货">
      <template #toolbar-tools>
        <Button type="primary" @click="createApi.open()">
          <Plus class="size-5" />
          登记到货计划
        </Button>
      </template>
    </Grid>
  </Page>
</template>
