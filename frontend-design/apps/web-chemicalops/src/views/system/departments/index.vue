<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemDepartmentApi } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';

import { Button, message, Modal } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteDepartmentApi, getDepartmentListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SystemDepartment' });

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
          return await getDepartmentListApi({
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
  } as VxeTableGridOptions<SystemDepartmentApi.SystemDepartment>,
});

function onActionClick({
  code,
  row,
}: OnActionClickParams<SystemDepartmentApi.SystemDepartment>) {
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

function onDelete(row: SystemDepartmentApi.SystemDepartment) {
  Modal.confirm({
    content: `停用后该部门下的用户将失去部门归属：${row.department_name}`,
    onOk: async () => {
      try {
        await deleteDepartmentApi(row.id);
        message.success(`已停用 ${row.department_name}`);
        onRefresh();
      } catch {
        // 错误提示已由请求层统一弹出
      }
    },
    okButtonProps: { danger: true },
    okText: '停用',
    title: '停用部门',
  });
}

function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <Grid table-title="组织架构">
      <template #toolbar-tools>
        <Button type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增部门
        </Button>
      </template>
    </Grid>
  </Page>
</template>
