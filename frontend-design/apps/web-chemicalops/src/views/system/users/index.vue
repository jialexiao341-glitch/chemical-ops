<script lang="ts" setup>
import type {
  OnActionClickParams,
  VxeTableGridOptions,
} from '#/adapter/vxe-table';
import type { SystemUserApi } from '#/api';

import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { Page, useVbenDrawer } from '@vben/common-ui';
import { Plus } from '@vben/icons';
import { useUserStore } from '@vben/stores';

import { Button, Input, message, Modal, Select } from 'antdv-next';

import { useVbenVxeGrid } from '#/adapter/vxe-table';
import {
  deleteUserApi, getSupplierBindingOptionsApi, getUserApi, getUserListApi,
  getUserSupplierBindingApi, setUserSupplierBindingApi,
  reviewRegistrationApi,
} from '#/api';

import { useColumns, useGridFormSchema } from './data';
import Form from './modules/form.vue';

defineOptions({ name: 'SystemUser' });
const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const canWriteUsers = hasAccessByCodes(['system.users.write']);
const isAdmin = userStore.userInfo?.roles?.includes('SYS_ADMIN') ?? false;
const reviewOpen = ref(false);
const reviewSaving = ref(false);
const reviewUser = ref<SystemUserApi.SystemUser>();
const reviewDecision = ref<'approve' | 'reject'>('approve');
const reviewReason = ref('');

async function saveReview() {
  if (!isAdmin || !reviewUser.value || reviewSaving.value) return;
  reviewSaving.value = true;
  try {
    await reviewRegistrationApi(reviewUser.value.id, reviewDecision.value, reviewReason.value.trim());
    message.success(reviewDecision.value === 'approve' ? '注册已批准，用户现在可以登录' : '注册申请已拒绝');
    reviewOpen.value = false;
    onRefresh();
  } catch {
    // 保持弹窗打开，错误由请求层提示。
  } finally {
    reviewSaving.value = false;
  }
}
const bindingOpen = ref(false);
const bindingLoading = ref(false);
const bindingSaving = ref(false);
const bindingUser = ref<SystemUserApi.SystemUser>();
const currentBinding = ref<SystemUserApi.SupplierBinding | null>(null);
const selectedSupplierId = ref<number>();
const bindingOptions = ref<SystemUserApi.SupplierBindingOption[]>([]);
const supplierOptions = computed(() => bindingOptions.value.map((supplier) => ({
  label: `${supplier.supplier_code} · ${supplier.supplier_name}`,
  value: supplier.id,
})));

async function openSupplierBinding(row: SystemUserApi.SystemUser) {
  if (!canWriteUsers || row.status !== 'ACTIVE' || row.role_codes?.length !== 1 || row.role_codes[0] !== 'SUPPLIER_PORTAL' || bindingLoading.value || bindingSaving.value) return;
  bindingUser.value = row;
  currentBinding.value = null;
  selectedSupplierId.value = undefined;
  bindingOptions.value = [];
  bindingOpen.value = true;
  bindingLoading.value = true;
  try {
    const [options, binding] = await Promise.all([
      getSupplierBindingOptionsApi(), getUserSupplierBindingApi(row.id),
    ]);
    bindingOptions.value = options;
    currentBinding.value = binding;
    if (binding && options.some((supplier) => supplier.id === binding.supplier_id)) {
      selectedSupplierId.value = binding.supplier_id;
    }
  } catch {
    bindingOpen.value = false;
  } finally {
    bindingLoading.value = false;
  }
}

async function saveSupplierBinding() {
  if (!canWriteUsers || !bindingUser.value || bindingLoading.value || bindingSaving.value) return;
  if (!selectedSupplierId.value) {
    message.warning('请选择要绑定的供应商');
    return;
  }
  bindingSaving.value = true;
  try {
    await setUserSupplierBindingApi(bindingUser.value.id, selectedSupplierId.value);
    message.success('供应商绑定已保存');
    bindingOpen.value = false;
  } catch {
    // 请求层展示错误，保留选择以便修正后重试。
  } finally {
    bindingSaving.value = false;
  }
}

const [FormDrawer, formDrawerApi] = useVbenDrawer({
  connectedComponent: Form,
  destroyOnClose: true,
});

const [Grid, gridApi] = useVbenVxeGrid({
  formOptions: {
    schema: useGridFormSchema(),
  },
  gridOptions: {
    columns: useColumns(onActionClick, Number(userStore.userInfo?.userId), isAdmin),
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
    case 'review-registration': {
      if (!isAdmin || row.status !== 'PENDING') return;
      reviewUser.value = row;
      reviewDecision.value = 'approve';
      reviewReason.value = '';
      reviewOpen.value = true;
      break;
    }
    case 'bind-supplier': {
      void openSupplierBinding(row);
      break;
    }
    case 'delete': {
      onDelete(row);
      break;
    }
    case 'edit': {
      // 列表行不含 role_ids，编辑前拉详情以便回填已绑定角色
      void (async () => {
        try {
          const detail = await getUserApi(row.id);
          formDrawerApi.setData({ ...row, ...detail }).open();
        } catch {
          // 详情失败时退回列表数据（角色不回填，保持旧行为）
          formDrawerApi.setData(row).open();
        }
      })();
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
        <Button v-if="isAdmin" @click="gridApi.formApi.setValues({ status: 'PENDING' }).then(onRefresh)">待审核注册</Button>
        <Button v-if="canWriteUsers" type="primary" @click="formDrawerApi.setData(null).open()">
          <Plus class="size-5" />
          新增用户
        </Button>
      </template>
    </Grid>
    <Modal v-model:open="reviewOpen" :confirm-loading="reviewSaving" title="审核注册申请"
      :closable="!reviewSaving" :mask-closable="!reviewSaving" :keyboard="!reviewSaving"
      :cancel-button-props="{ disabled: reviewSaving }" @ok="saveReview">
      <div v-if="reviewUser" class="space-y-4 py-2">
        <div><div class="mb-1 text-sm text-muted-foreground">申请人</div><div class="font-medium">{{ reviewUser.display_name }} · {{ reviewUser.username }}</div></div>
        <div><div class="mb-1 text-sm text-muted-foreground">申请角色</div><div>{{ reviewUser.role_names.join('、') || '角色已失效' }}</div></div>
        <div><label for="registration-decision" class="mb-1 block text-sm text-muted-foreground">审核结果</label><Select id="registration-decision" v-model:value="reviewDecision" class="w-full" :disabled="reviewSaving" :options="[{ label: '批准注册', value: 'approve' }, { label: '拒绝注册', value: 'reject' }]" /></div>
        <div><label for="registration-reason" class="mb-1 block text-sm text-muted-foreground">审核说明</label><Input.TextArea id="registration-reason" v-model:value="reviewReason" :disabled="reviewSaving" :maxlength="500" :rows="3" placeholder="填写审核说明（选填）" /></div>
      </div>
    </Modal>
    <Modal
      v-model:open="bindingOpen"
      :confirm-loading="bindingSaving"
      :ok-button-props="{ disabled: bindingLoading || !selectedSupplierId || !canWriteUsers }"
      :cancel-button-props="{ disabled: bindingSaving }"
      :closable="!bindingSaving"
      :mask-closable="!bindingSaving"
      :keyboard="!bindingSaving"
      title="绑定供应商"
      @ok="saveSupplierBinding"
    >
      <div v-if="bindingUser" class="space-y-4 py-2">
        <div><div class="mb-1 text-sm text-muted-foreground">登录账号</div><div class="font-medium">{{ bindingUser.username }} · {{ bindingUser.display_name }}</div></div>
        <div><div class="mb-1 text-sm text-muted-foreground">当前绑定</div><div>{{ bindingLoading ? '加载中…' : currentBinding ? `${currentBinding.supplier_code} · ${currentBinding.supplier_name}` : '未绑定' }}<span v-if="currentBinding && (currentBinding.status !== 'ACTIVE' || currentBinding.supplier_status !== 'ACTIVE')">（已停用）</span></div></div>
        <div>
          <label for="supplier-binding-select" class="mb-1 block text-sm text-muted-foreground">可绑定供应商</label>
          <Select
            id="supplier-binding-select"
            v-model:value="selectedSupplierId"
            :options="supplierOptions"
            :loading="bindingLoading"
            :disabled="bindingLoading || bindingSaving"
            class="w-full"
            show-search
            option-filter-prop="label"
            placeholder="按供应商编号或名称搜索"
            :not-found-content="bindingLoading ? '加载中…' : '暂无匹配的启用供应商'"
          />
        </div>
        <div class="text-sm text-muted-foreground">仅可绑定启用的供应商。每个账号绑定一个供应商，保存后替换原有绑定；门户操作权限由账号角色决定。</div>
      </div>
    </Modal>
  </Page>
</template>
