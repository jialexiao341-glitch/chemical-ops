<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemRoleApi } from '#/api';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteRoleApi, getRoleListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SystemRole' });
const { hasAccessByCodes } = useAccess();
const canWriteRoles = hasAccessByCodes(['system.roles.write']);

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
          return await getRoleListApi({
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
  } as VxeTableGridOptions<SystemRoleApi.SystemRole>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<SystemRoleApi.SystemRole>) {
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

function onDelete(row: SystemRoleApi.SystemRole) {
  Modal.confirm({
    content: `停用后绑定该角色的用户将失去对应权限：${row.role_name}`,
    onOk: async () => {
      const hideLoading = message.loading({
        content: `正在停用 ${row.role_name}`,
        duration: 0,
        key: 'action_process_msg',
      });
      try {
        await deleteRoleApi(row.id);
        message.success({
          content: `已停用 ${row.role_name}`,
          key: 'action_process_msg',
        });
        onRefresh();
      } catch {
        hideLoading();
      }
    },
    okButtonProps: { danger: true },
    okText: '停用',
    title: '停用角色',
  });
}

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="角色管理">
      <template #toolbar-tools>
        <Button v-if="canWriteRoles" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增角色
        </Button>
      </template>
    </Grid>
  </Page>
</template>
