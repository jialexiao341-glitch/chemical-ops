import type { PageQuery, PageResult } from '#/api/request';

import { requestClient } from '#/api/request';

export namespace InventoryApi {
  /** 仓库 */
  export interface Warehouse {
    address?: null | string;
    created_at?: string;
    id: number;
    manager_id?: null | number;
    note?: null | string;
    region?: null | string;
    status?: string;
    warehouse_code: string;
    warehouse_name: string;
  }

  /** 库位 */
  export interface Location {
    created_at?: string;
    id: number;
    location_code: string;
    location_name: string;
    note?: null | string;
    status?: string;
    warehouse_id?: number;
  }

  /** 库存余额 */
  export interface InventoryBalance {
    batch_id?: number;
    created_at?: string;
    id: number;
    location_id: number;
    locked_quantity: string;
    product_id: number;
    quantity: string;
    status: string;
    unit_id: number;
    updated_at?: string;
    warehouse_id: number;
  }

  /** 库存流水 */
  export interface InventoryTransaction {
    batch_id?: number;
    created_at?: string;
    delivery_item_id?: null | number;
    id: number;
    location_id: number;
    note?: null | string;
    operator_id?: number;
    product_id: number;
    quantity: string;
    source_id?: null | number;
    source_type?: null | string;
    transaction_no: string;
    transaction_type: string;
    unit_id: number;
    warehouse_id: number;
  }

  /** 库存状态变更记录 */
  export interface BalanceStatusLog {
    after_status?: string;
    balance_id?: number;
    before_status?: string;
    created_at?: string;
    id: number;
    operator_id?: number;
    reason: string;
  }

  /** 入库结果 */
  export interface InboundResult {
    balances?: InventoryBalance[];
    delivery_id: number;
    transaction_count: number;
    transactions?: InventoryTransaction[];
  }

  /** 有效期预警 */
  export interface ExpiryAlert {
    alert_level: string;
    batch_id: number;
    batch_no?: null | string;
    days_remaining: number;
    expiry_date: string;
    location_id: number;
    product_id: number;
    quantity: string;
    warehouse_id: number;
  }

  /** FIFO 出库成本分摊 */
  export interface FifoAllocation {
    batch_id?: number;
    cost_layer_id?: number;
    id: number;
    quantity: string;
    request_id?: number;
    total_cost: string;
    unit_cost: string;
  }

  export interface FifoOutbound {
    allocations?: FifoAllocation[];
    created_at?: string;
    currency_code?: string;
    id: number;
    issued_quantity: string;
    location_id: number;
    note?: null | string;
    operator_id?: number;
    product_id: number;
    request_no: string;
    requested_quantity: string;
    status: string;
    total_cost: string;
    unit_id: number;
    warehouse_id: number;
  }

  export interface BalanceListParams extends PageQuery {
    batch_id?: number;
    product_id?: number;
    warehouse_id?: number;
  }

  export interface TransactionListParams extends PageQuery {
    product_id?: number;
    transaction_type?: string;
  }
}

/** 查询仓库列表（不分页） */
export async function getWarehouseListApi(options?: { silent?: boolean }) {
  return requestClient.get<InventoryApi.Warehouse[]>(
    '/inventory/warehouses',
    options,
  );
}

/** 创建仓库 */
export async function createWarehouseApi(data: {
  address?: string;
  manager_id?: null | number;
  note?: string;
  region?: string;
  warehouse_code: string;
  warehouse_name: string;
}) {
  return requestClient.post<InventoryApi.Warehouse>(
    '/inventory/warehouses',
    data,
  );
}

/** 查询某仓库下的库位（不分页） */
export async function getLocationListApi(warehouseId: number) {
  return requestClient.get<InventoryApi.Location[]>(
    `/inventory/warehouses/${warehouseId}/locations`,
  );
}

/** 创建库位 */
export async function createLocationApi(
  warehouseId: number,
  data: { location_code: string; location_name: string; note?: string },
) {
  return requestClient.post<InventoryApi.Location>(
    `/inventory/warehouses/${warehouseId}/locations`,
    data,
  );
}

/**
 * 执行库存入库。
 * 仅允许质量验收通过的到货单入库，同一到货明细只能入库一次。
 */
export async function createInboundApi(data: {
  delivery_id: number;
  location_id: number;
  note?: string;
  warehouse_id: number;
}) {
  return requestClient.post<InventoryApi.InboundResult>(
    '/inventory/inbounds',
    data,
  );
}

/** 分页查询库存余额 */
export async function getBalanceListApi(params?: InventoryApi.BalanceListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<InventoryApi.InventoryBalance>>(
    '/inventory/balances',
    { ...options, params },
  );
}

/** 冻结库存余额（不改变数量） */
export async function freezeBalanceApi(id: number, reason: string) {
  return requestClient.post<InventoryApi.InventoryBalance>(
    `/inventory/balances/${id}/freeze`,
    { reason },
  );
}

/** 解冻库存余额 */
export async function unfreezeBalanceApi(id: number, reason: string) {
  return requestClient.post<InventoryApi.InventoryBalance>(
    `/inventory/balances/${id}/unfreeze`,
    { reason },
  );
}

/** 查询库存冻结/解冻历史 */
export async function getBalanceStatusLogsApi(
  id: number,
  params?: PageQuery,
) {
  return requestClient.get<PageResult<InventoryApi.BalanceStatusLog>>(
    `/inventory/balances/${id}/status-logs`,
    { params },
  );
}

/** 分页查询库存流水 */
export async function getTransactionListApi(params?: InventoryApi.TransactionListParams, options?: { silent?: boolean }) {
  return requestClient.get<PageResult<InventoryApi.InventoryTransaction>>(
    '/inventory/transactions',
    { ...options, params },
  );
}

/**
 * 按 FIFO 顺序出库并生成成本分摊。
 * `request_no` 作为请求级幂等键。
 */
export async function createFifoOutboundApi(data: {
  location_id: number;
  note?: string;
  product_id: number;
  quantity: number | string;
  request_no: string;
  unit_id: number;
  warehouse_id: number;
}) {
  return requestClient.post<InventoryApi.FifoOutbound>(
    '/inventory/fifo-outbounds',
    data,
  );
}

/** 查询库存有效期预警 */
export async function getExpiryAlertsApi(days: number = 30, options?: { silent?: boolean }) {
  return requestClient.get<InventoryApi.ExpiryAlert[]>(
    '/inventory/expiry-alerts',
    { ...options, params: { days } },
  );
}
