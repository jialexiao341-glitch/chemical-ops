<script lang="ts" setup>
import type { OnActionClickParams, VxeTableGridOptions } from '#/adapter/vxe-table';
import type { ChemicalApi } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteChemicalApi, getChemicalListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'ChemicalList' });

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
    submitOnChange: false,
  },
  gridOptions: {
    columns: useColumns(onActionClick),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getChemicalListApi({
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
  } as VxeTableGridOptions<ChemicalApi.Chemical>,
});

function onActionClick({ code, row }: OnActionClickParams<ChemicalApi.Chemical>) {
  switch (code) {
    case 'delete': {
      onDelete(row);
      break;
    }
    case 'edit': {
      onEdit(row);
      break;
    }
  }
}

function onCreate() {
  formDrawerApi.setData(null).open();
}

function onEdit(row: ChemicalApi.Chemical) {
  formDrawerApi.setData(row).open();
}

function onDelete(row: ChemicalApi.Chemical) {
  const hideLoading = message.loading({
    content: `正在停用 ${row.chemical_name}`,
    duration: 0,
    key: 'action_process_msg',
  });
  deleteChemicalApi(row.id)
    .then(() => {
      message.success({
        content: `已停用 ${row.chemical_name}`,
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
    <Grid table-title="化学品主数据">
      <template #toolbar-tools>
        <Button type="primary" @click="onCreate">
          <Plus class="size-5" />
          新增化学品
        </Button>
      </template>
    </Grid>
  </Page>
</template>
