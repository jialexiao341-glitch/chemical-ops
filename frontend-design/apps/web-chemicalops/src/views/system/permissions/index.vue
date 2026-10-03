<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemPermissionApi } from '#/api';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deletePermissionApi, getPermissionListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SystemPermission' });
const { hasAccessByCodes } = useAccess();
const canWritePermissions = hasAccessByCodes(['system.permissions.write']);

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
          return await getPermissionListApi({
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
  } as VxeTableGridOptions<SystemPermissionApi.SystemPermission>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<SystemPermissionApi.SystemPermission>) {
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

/**
 * 删除权限。
 * 权限是物理删除，且已绑定角色的权限不允许删除，后端会返回中文提示。
 */
function onDelete(row: SystemPermissionApi.SystemPermission) {
  Modal.confirm({
    content: `删除后不可恢复，且已绑定该权限的角色会失去它：${row.permission_name}`,
    onOk: async () => {
      try {
        await deletePermissionApi(row.id);
        message.success(`已删除 ${row.permission_name}`);
        onRefresh();
      } catch {
        // 错误提示已由请求层统一弹出
      }
    },
    okButtonProps: { danger: true },
    okText: '删除',
    title: '删除权限',
  });
}

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="权限管理">
      <template #toolbar-tools>
        <Button v-if="canWritePermissions" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增权限
        </Button>
      </template>
    </Grid>
  </Page>
</template>
