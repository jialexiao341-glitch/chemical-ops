<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { ProductApi } from '#/api';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';

import { Button, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteProductApi, getProductListApi } from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';
import QualityStandard from './modules/quality-standard.vue';

defineOptions({ name: 'ProductList' });
const { hasAccessByCodes } = useAccess();
const canManageProducts = hasAccessByCodes(['master.products.write']);

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [StandardDrawer, standardDrawerApi] = useVbenDrawer({
  connectedComponent: QualityStandard,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick, canManageProducts),
    height: 'auto',
    keepSource: true,
    proxyConfig: {
      ajax: {
        query: async ({ page }, formValues) => {
          return await getProductListApi({
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
  } as VxeTableGridOptions<ProductApi.Product>,
});

/** 根据表格操作类型打开编辑表单或检测标准抽屉。 */
function onActionClick({
  code,
  row,
}: OnActionClickParams<ProductApi.Product>) {
  switch (code) {
    case 'standard': {
      standardDrawerApi.setData(row).open();
      break;
    }
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

/** 停用选定产品，并在操作完成后刷新列表。 */
function onDelete(row: ProductApi.Product) {
  const hideLoading = message.loading({
    content: `正在停用 ${row.product_name}`,
    duration: 0,
    key: 'action_process_msg',
  });
  deleteProductApi(row.id)
    .then(() => {
      message.success({
        content: `已停用 ${row.product_name}`,
        key: 'action_process_msg',
      });
      onRefresh();
    })
    .catch(() => {
      hideLoading();
    });
}

/** 重新查询当前产品列表。 */
function onRefresh() {
  gridApi.query();
}
</script>

<template>
  <Page auto-content-height>
    <FormDrawer @success="onRefresh" />
    <StandardDrawer />
    <Grid table-title="产品规格">
      <template #toolbar-tools>
        <Button v-if="canManageProducts" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增产品规格
        </Button>
      </template>
    </Grid>
  </Page>
</template>
