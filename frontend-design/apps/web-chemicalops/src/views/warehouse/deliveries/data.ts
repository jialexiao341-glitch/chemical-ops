import type { VbenFormSchema } from '#/adapter/form';
import type {
  OnActionClickFn,
  VxeTableGridColumns,
} from '#/adapter/vxe-table';
import type { DeliveryApi } from '#/api';

import { DELIVERY_STATUS_DICT } from '#/constants/dictionary';
import { formatDate, formatQuantity } from '#/utils/format';

/** 列表筛选条件 */
export function useGridFormSchema(): VbenFormSchema[] {
  return [
    {
      component: 'Input',
      componentProps: { allowClear: true, placeholder: '请输入到货单编号' },
      fieldName: 'keyword',
      label: '到货单编号',
    },
    {
      component: 'Select',
      componentProps: {
        allowClear: true,
        options: DELIVERY_STATUS_DICT.options(),
        placeholder: '全部状态',
      },
      fieldName: 'status',
      label: '状态',
    },
  ];
}

/** 列表列定义 */
export function useColumns(
  onActionClick: OnActionClickFn<DeliveryApi.Delivery>,
  resolveSupplier: (id?: null | number) => string,
): VxeTableGridColumns {
  return [
    { field: 'delivery_no', minWidth: 180, title: '到货单编号' },
    {
      field: 'supplier_id',
      formatter: ({ cellValue }: { cellValue: any }) =>
        resolveSupplier(cellValue),
      minWidth: 180,
      title: '供应商',
    },
    { field: 'po_id', title: '采购订单 ID', width: 120 },
    {
      field: 'shipment_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '发货日期',
      width: 120,
    },
    {
      field: 'expected_arrival_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '预计到货',
      width: 120,
    },
    {
      field: 'actual_arrival_date',
      formatter: ({ cellValue }: { cellValue: any }) => formatDate(cellValue),
      title: '实际到货',
      width: 120,
    },
    { field: 'logistics_company', title: '物流公司', width: 140 },
    {
      cellRender: {
        name: 'CellTag',
        options: DELIVERY_STATUS_DICT.items,
      },
      field: 'status',
      title: '状态',
      width: 110,
    },
    {
      align: 'center',
      cellRender: {
        attrs: {
          nameField: 'delivery_no',
          nameTitle: '到货单',
          onClick: onActionClick,
        },
        name: 'CellOperation',
        options: [
          {
            // 只有在途状态可以收货，其余状态按钮置灰
            code: 'receive',
            disabled: (row: DeliveryApi.Delivery) =>
              row.status !== 'IN_TRANSIT',
            auth: 'warehouse.deliveries.write',
            text: '确认收货',
          },
        ],
      },
      field: 'operation',
      fixed: 'right',
      title: '操作',
      width: 140,
    },
  ];
}

/** 到货明细的登记行（登记到货计划时使用） */
export interface PlannedRow {
  batch_no?: string;
  document_complete?: boolean;
  expiry_date?: string;
  note?: string;
  package_spec?: string;
  planned_quantity?: number | string;
  po_item_id: number;
  productName: string;
  production_date?: string;
  /** 订单剩余未到货数量，用于校验与提示 */
  remaining: string;
  unitName: string;
}

/** 收货明细行 */
export interface ReceiveRow extends PlannedRow {
  actual_quantity?: number | string;
  delivery_item_id: number;
  plannedText: string;
  short_quantity?: number | string;
}

/** 数量展示辅助 */
export function formatPlanned(value: null | number | string | undefined) {
  return formatQuantity(value);
}
