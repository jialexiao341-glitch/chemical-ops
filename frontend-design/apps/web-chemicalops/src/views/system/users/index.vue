<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemUserApi } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteUserApi, getUserListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SystemUser' });

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
          return await getUserListApi({
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
  } as VxeTableGridOptions<SystemUserApi.SystemUser>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<SystemUserApi.SystemUser>) {
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

/** 停用用户，需要二次确认 */
function onDelete(row: SystemUserApi.SystemUser) {
  Modal.confirm({
    content: `停用后该用户将无法登录：${row.display_name}`,
    onOk: async () => {
      const hideLoading = message.loading({
        content: `正在停用 ${row.display_name}`,
        duration: 0,
        key: 'action_process_msg',
      });
      try {
        await deleteUserApi(row.id);
        message.success({
          content: `已停用 ${row.display_name}`,
          key: 'action_process_msg',
        });
        onRefresh();
      } catch {
        hideLoading();
      }
    },
    okButtonProps: { danger: true },
    okText: '停用',
    title: '停用用户',
  });
}

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="系统用户">
      <template #toolbar-tools>
        <Button type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增用户
        </Button>
      </template>
    </Grid>
  </Page>
</template>
