<script lang="ts" setup>
import type { ReplenishmentApi } from '#/api';

import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenDrawer } from '@vben/common-ui';
import { useUserStore } from '@vben/stores';

import {
  Button,
  Descriptions,
  DescriptionsItem,
  Empty,
  Input,
  message,
  Modal,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import {
  approveReplenishmentApi,
  cancelReplenishmentApi,
  getReplenishmentApi,
  rejectReplenishmentApi,
  submitReplenishmentApi,
} from '#/api';
import { APPROVAL_FLOW_STATUS_DICT } from '#/constants/dictionary';
import { formatDateTime, formatQuantity } from '#/utils/format';

const emit = defineEmits(['success']);

const { hasAccessByCodes } = useAccess();
const userStore = useUserStore();
const canWrite = hasAccessByCodes(['procurement.replenishment.write']);
const canApprove = hasAccessByCodes(['procurement.replenishment.approve']);

const detail = ref<ReplenishmentApi.Replenishment>();
const isOwnApplicant = computed(
  () => Number(detail.value?.applicant_id) === Number(userStore.userInfo?.userId),
);
const loading = ref(false);
const acting = ref(false);
const rejectOpen = ref(false);
const rejectReason = ref('');

const itemColumns = [
  { dataIndex: 'product_name', key: 'product_name', title: '产品' },
  { dataIndex: 'product_code', key: 'product_code', title: '产品编码', width: 150 },
  { dataIndex: 'requested_quantity', key: 'requested_quantity', title: '补货数量', width: 100 },
  { dataIndex: 'unit_name', key: 'unit_name', title: '单位', width: 70 },
  { dataIndex: 'expected_date', key: 'expected_date', title: '期望到货', width: 120 },
  { dataIndex: 'status', key: 'status', title: '状态', width: 90 },
];

const [Drawer, drawerApi] = useVbenDrawer<null | { id: number }>({
  footer: false,
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    const data = drawerApi.getData();
    detail.value = undefined;
    rejectOpen.value = false;
    rejectReason.value = '';
    if (!data?.id) {
      return;
    }
    await reload(data.id);
  },
});

async function reload(id: number) {
  loading.value = true;
  try {
    detail.value = await getReplenishmentApi(id);
  } catch (error: any) {
    message.error(error?.message || '补货申请加载失败');
  } finally {
    loading.value = false;
  }
}

async function runAction(action: () => Promise<unknown>, successText: string) {
  acting.value = true;
  try {
    await action();
    message.success(successText);
    if (detail.value) {
      await reload(detail.value.id);
    }
    emit('success');
  } catch (error: any) {
    message.error(error?.message || '操作失败');
  } finally {
    acting.value = false;
  }
}

function submit() {
  if (!detail.value) return;
  const id = detail.value.id;
  Modal.confirm({
    content: '提交后进入补货审批，审批通过前不能修改明细。',
    okText: '提交',
    onOk: () => runAction(() => submitReplenishmentApi(id), '补货申请已提交'),
  });
}

function cancel() {
  if (!detail.value) return;
  const id = detail.value.id;
  Modal.confirm({
    content: '取消后该补货申请不能继续提交。',
    okText: '取消申请',
    okButtonProps: { danger: true },
    onOk: () => runAction(() => cancelReplenishmentApi(id), '补货申请已取消'),
  });
}

function approve() {
  if (!detail.value) return;
  const id = detail.value.id;
  Modal.confirm({
    content: '确认审批通过这条补货申请？',
    okText: '审批通过',
    onOk: () => runAction(() => approveReplenishmentApi(id), '补货申请已通过审批'),
  });
}

async function confirmReject() {
  if (!detail.value) return;
  const reason = rejectReason.value.trim();
  if (!reason) {
    message.warning('请填写驳回原因');
    return;
  }
  const id = detail.value.id;
  rejectOpen.value = false;
  await runAction(() => rejectReplenishmentApi(id, reason), '补货申请已驳回');
}
</script>

<template>
  <Drawer :title="detail?.replenishment_no || '补货申请'" class="w-[760px]">
    <Spin :spinning="loading">
      <div v-if="detail" class="space-y-4">
        <Descriptions bordered :column="2" size="small">
          <DescriptionsItem label="状态">
            <Tag :color="APPROVAL_FLOW_STATUS_DICT.color(detail.status)">
              {{ APPROVAL_FLOW_STATUS_DICT.label(detail.status) }}
            </Tag>
          </DescriptionsItem>
          <DescriptionsItem label="供应商">
            {{ detail.supplier_name || detail.supplier_code || `#${detail.supplier_id}` }}
          </DescriptionsItem>
          <DescriptionsItem label="申请人">
            {{ detail.applicant_name || `#${detail.applicant_id}` }}
          </DescriptionsItem>
          <DescriptionsItem label="创建时间">
            {{ formatDateTime(detail.created_at) }}
          </DescriptionsItem>
          <DescriptionsItem label="补货原因" :span="2">
            {{ detail.reason }}
          </DescriptionsItem>
          <DescriptionsItem v-if="detail.reject_reason" label="驳回原因" :span="2">
            {{ detail.reject_reason }}
          </DescriptionsItem>
        </Descriptions>

        <Table
          :columns="itemColumns"
          :data-source="detail.items || []"
          :pagination="false"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'product_name'">
              {{ record.product_name || `#${record.product_id}` }}
            </template>
            <template v-else-if="column.key === 'requested_quantity'">
              {{ formatQuantity(record.requested_quantity) }}
            </template>
            <template v-else-if="column.key === 'status'">
              <Tag>{{ record.status }}</Tag>
            </template>
          </template>
        </Table>

        <div class="flex flex-wrap justify-end gap-2">
          <template v-if="canWrite && ['DRAFT', 'REJECTED'].includes(detail.status)">
            <Button :loading="acting" @click="cancel">取消申请</Button>
            <Button :loading="acting" type="primary" @click="submit">提交审批</Button>
          </template>
          <template v-if="canApprove && detail.status === 'SUBMITTED'">
            <div v-if="isOwnApplicant" class="text-sm text-amber-700">
              不能审批本人经办的补货申请，请由其他有权限的审批人处理。
            </div>
            <template v-else>
              <Button :loading="acting" danger @click="rejectOpen = true">驳回</Button>
              <Button :loading="acting" type="primary" @click="approve">审批通过</Button>
            </template>
          </template>
          <div v-if="detail.status === 'APPROVED'" class="text-sm text-muted-foreground">
            已批准，待关联采购订单完成补货。
          </div>
        </div>
      </div>
      <Empty v-else description="未找到补货申请" />
    </Spin>

    <Modal v-model:open="rejectOpen" title="驳回补货申请" @ok="confirmReject">
      <Input.TextArea
        v-model:value="rejectReason"
        :maxlength="1000"
        :rows="3"
        placeholder="请填写驳回原因"
      />
    </Modal>
  </Drawer>
</template>
