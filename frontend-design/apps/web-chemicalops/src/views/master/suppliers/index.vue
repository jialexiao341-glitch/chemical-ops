<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SupplierApi } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteSupplierApi, getSupplierListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SupplierList' });

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getSupplierListApi({
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
  } as VxeTableGridOptions<SupplierApi.Supplier>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<SupplierApi.Supplier>) {
  switch (code) {
    case 'delete': {
      onDelete(row);
      break;
    }
    case 'edit': {
      formDrawerApi.setData(row).open();
      break;
    }
  }
}

function onDelete(row: SupplierApi.Supplier) {
  const hideLoading = message.loading({
    content: `正在停用 ${row.supplier_name}`,
    duration: 0,
    key: 'action_process_msg',
  });
  deleteSupplierApi(row.id)
    .then(() => {
      message.success({
        content: `已停用 ${row.supplier_name}`,
        key: 'action_process_msg',
      });
      onRefresh();
    })
    .catch(() => {
      hideLoading();
    });
}

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="供应商主数据">
      <template #toolbar-tools>
        <Button type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增供应商
        </Button>
      </template>
    </Grid>
  </Page>
</template>
