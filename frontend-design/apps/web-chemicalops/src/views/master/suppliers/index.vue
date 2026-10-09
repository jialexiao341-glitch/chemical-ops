<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SupplierApi } from '#/api';

import { onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { Page, useVbenDrawer } from '@vben/common-ui';
import { useAccess } from '@vben/access';
import { Plus } from '@vben/icons';

import { Button, message } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import { deleteSupplierApi, getSupplierListApi } from '#/api';
import { applyAiFiltersToList } from '#/utils/ai-list-filters';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';
import BusinessInsightDrawer from '#/views/ai/workspace/modules/business-insight-drawer.vue';

defineOptions({ name: 'SupplierList' });
const insightDrawer = ref<{ open: (kind: string, id: number) => void }>();
const route = useRoute();
const { hasAccessByCodes } = useAccess();
const canManageSuppliers = hasAccessByCodes(['master.suppliers.write']);

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(
      onActionClick,
      [
        'procurement.orders.read',
        'warehouse.deliveries.read',
        'quality.acceptances.read',
        'ai.workspace.read',
      ].every((code) => hasAccessByCodes([code])),
    ),
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
    case 'supplier-score': {
      insightDrawer.value?.open(code, row.id);
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

onMounted(async () => {
  await applyAiFiltersToList('suppliers', route.query.ai_filters, gridApi.formApi);
  gridApi.query();
});

watch(
  () => route.query.ai_filters,
  async (rawQuery) => {
    if (await applyAiFiltersToList('suppliers', rawQuery, gridApi.formApi)) {
      gridApi.query();
    }
  },
);
</script>

<template>
  <Page auto-content-height>
    <BusinessInsightDrawer ref="insightDrawer" />
    <FormDrawer @success="onRefresh" />
    <Grid table-title="供应商主数据">
      <template #toolbar-tools>
        <Button v-if="canManageSuppliers" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增供应商
        </Button>
      </template>
    </Grid>
  </Page>
</template>
