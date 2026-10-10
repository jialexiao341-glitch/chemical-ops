<script lang="ts" setup>
import type { PlannedRow } from '../data';

import { computed, ref } from 'vue';

import { useAccess } from '@vben/access';
import { useVbenModal } from '@vben/common-ui';

import {
  Alert,
  Checkbox,
  DatePicker,
  Empty,
  Input,
  InputNumber,
  message,
  Select,
  Spin,
  Table,
  Tag,
} from 'antdv-next';

import {
  createDeliveryApi,
  getPurchaseOrderApi,
  getPurchaseOrderListApi,
} from '#/api';
import { formatQuantity } from '#/utils/format';
import { getUnitNameMap } from '#/utils/lookup';

const { hasAccessByCodes } = useAccess();
const canConfirm = computed(() => hasAccessByCodes(['warehouse.deliveries.write']));
const emit = defineEmits(['success']);

/**
 * 登记到货计划。
 *
 * 到货明细必须挂在采购订单明细上，因此先选订单，再按明细填写
 * 计划到货数量与批次信息；剩余可到货数量由订单数量减去已收数量得出。
 */
const poId = ref<number>();
const poOptions = ref<Array<{ label: string; value: number }>>([]);
const shipmentDate = ref<string>();
const expectedArrivalDate = ref<string>();
const logisticsCompany = ref('');
const trackingNo = ref('');
const note = ref('');
const rows = ref<PlannedRow[]>([]);
const loading = ref(false);
const loadingItems = ref(false);
const submitting = ref(false);

const totalPlanned = computed(() =>
  rows.value.reduce((sum, row) => sum + Number(row.planned_quantity || 0), 0),
);

const [Modal, modalApi] = useVbenModal({
  async onConfirm() {
    if (!canConfirm.value) return;
    if (!poId.value) {
      message.warning('请先选择采购订单');
      return;
    }
    const items = rows.value.filter(
      (row) => Number(row.planned_quantity || 0) > 0,
    );
    if (items.length === 0) {
      message.warning('请至少填写一条到货明细的计划数量');
      return;
    }
    submitting.value = true;
    modalApi.lock();
    try {
      await createDeliveryApi({
        expected_arrival_date: expectedArrivalDate.value,
        items: items.map((row) => ({
          batch_no: row.batch_no || undefined,
          document_complete: row.document_complete ?? false,
          expiry_date: row.expiry_date,
          note: row.note || undefined,
          package_spec: row.package_spec || undefined,
          planned_quantity: row.planned_quantity as number,
          po_item_id: row.po_item_id,
          production_date: row.production_date,
        })),
        logistics_company: logisticsCompany.value || undefined,
        note: note.value || undefined,
        po_id: poId.value,
        shipment_date: shipmentDate.value,
        tracking_no: trackingNo.value || undefined,
      });
      message.success('到货计划已登记');
      emit('success');
      modalApi.close();
    } catch {
      // 请求层已统一弹出后端返回的中文错误，这里保持弹窗打开，
      // 让用户修正后重新提交；不吞掉异常会产生未捕获的 Promise 拒绝。
    } finally {
      submitting.value = false;
      modalApi.unlock();
    }
  },
  async onOpenChange(isOpen) {
    if (!isOpen) {
      return;
    }
    poId.value = undefined;
    shipmentDate.value = undefined;
    expectedArrivalDate.value = undefined;
    logisticsCompany.value = '';
    trackingNo.value = '';
    note.value = '';
    rows.value = [];
    loading.value = true;
    try {
      // 只有已下单（ORDERED）或部分到货（PARTIAL）的订单可以登记到货
      const [ordered, partial] = await Promise.all([
        getPurchaseOrderListApi({ page: 1, page_size: 100, status: 'ORDERED' }),
        getPurchaseOrderListApi({ page: 1, page_size: 100, status: 'PARTIAL' }),
      ]);
      poOptions.value = [...ordered.items, ...partial.items].map((item) => ({
        label: `${item.po_no}（剩余可到货）`,
        value: item.id,
      }));
    } finally {
      loading.value = false;
    }
  },
});

async function onPoChange(value: number) {
  rows.value = [];
  if (!value) {
    return;
  }
  loadingItems.value = true;
  try {
    const [order, unitMap] = await Promise.all([
      getPurchaseOrderApi(value),
      getUnitNameMap(),
    ]);
    rows.value = (order.items ?? []).map((item) => {
      const remaining =
        Number(item.order_quantity) - Number(item.received_quantity ?? 0);
      return {
        batch_no: '',
        document_complete: false,
        expiry_date: undefined,
        note: '',
        package_spec: '',
        planned_quantity: remaining > 0 ? remaining : 0,
        po_item_id: item.id,
        productName: item.product_name_snapshot,
        production_date: undefined,
        remaining: formatQuantity(remaining),
        unitName: unitMap.get(item.unit_id) ?? `#${item.unit_id}`,
      };
    });
  } finally {
    loadingItems.value = false;
  }
}

const columns = [
  { key: 'productName', title: '物料', width: 180 },
  { key: 'remaining', title: '剩余可到货', width: 130 },
  { key: 'planned_quantity', title: '计划到货数量', width: 170 },
  { key: 'batch_no', title: '批次号', width: 150 },
  { key: 'package_spec', title: '包装规格', width: 140 },
  { key: 'production_date', title: '生产日期', width: 150 },
  { key: 'expiry_date', title: '有效期至', width: 150 },
  { key: 'document_complete', title: '单证齐全', width: 100 },
];
</script>

<template>
  <Modal :show-confirm-button="canConfirm" title="登记到货计划" class="w-[1100px] max-w-[100vw]">
    <Spin :spinning="loading">
      <div class="space-y-4 px-1">
        <Alert
          message="到货计划必须关联已下单或部分到货的采购订单；短交会在收货时自动生成异常。"
          type="info"
          show-icon
        />
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <div class="mb-2 text-sm">采购订单</div>
            <Select
              v-model:value="poId"
              :options="poOptions"
              class="w-full"
              placeholder="请选择采购订单"
              show-search
              @change="onPoChange"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">发货日期</div>
            <DatePicker
              v-model:value="shipmentDate"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">预计到货日期</div>
            <DatePicker
              v-model:value="expectedArrivalDate"
              class="w-full"
              value-format="YYYY-MM-DD"
            />
          </div>
          <div>
            <div class="mb-2 text-sm">物流公司</div>
            <Input v-model:value="logisticsCompany" :maxlength="100" />
          </div>
          <div>
            <div class="mb-2 text-sm">运单号</div>
            <Input v-model:value="trackingNo" :maxlength="100" />
          </div>
          <div>
            <div class="mb-2 text-sm">备注</div>
            <Input v-model:value="note" :maxlength="255" />
          </div>
        </div>

        <Spin :spinning="loadingItems">
          <Empty
            v-if="rows.length === 0"
            :description="poId ? '该订单没有可到货明细' : '请先选择采购订单'"
          />
          <Table
            v-else
            :columns="columns"
            :data-source="rows"
            :pagination="false"
            row-key="po_item_id"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'productName'">
                {{ record.productName }}
                <Tag class="ml-1">{{ record.unitName }}</Tag>
              </template>
              <template v-else-if="column.key === 'planned_quantity'">
                <InputNumber
                  v-model:value="record.planned_quantity"
                  :max="Number(record.remaining)"
                  :min="0"
                  class="w-full"
                />
              </template>
              <template v-else-if="column.key === 'batch_no'">
                <Input v-model:value="record.batch_no" :maxlength="64" />
              </template>
              <template v-else-if="column.key === 'package_spec'">
                <Input v-model:value="record.package_spec" :maxlength="100" />
              </template>
              <template v-else-if="column.key === 'production_date'">
                <DatePicker
                  v-model:value="record.production_date"
                  class="w-full"
                  value-format="YYYY-MM-DD"
                />
              </template>
              <template v-else-if="column.key === 'expiry_date'">
                <DatePicker
                  v-model:value="record.expiry_date"
                  class="w-full"
                  value-format="YYYY-MM-DD"
                />
              </template>
              <template v-else-if="column.key === 'document_complete'">
                <Checkbox v-model:checked="record.document_complete" />
              </template>
            </template>
          </Table>
        </Spin>

        <div v-if="rows.length > 0" class="text-muted-foreground text-right text-sm">
          计划到货合计：{{ formatQuantity(totalPlanned) }}
        </div>
      </div>
    </Spin>
  </Modal>
</template>
