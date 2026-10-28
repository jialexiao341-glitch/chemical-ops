import { requestClient } from '#/api/request';

export namespace DashboardApi {
  /** 按计量单位汇总的库存量 */
  export interface InventoryUnit {
    quantity: string;
    unit_code: string;
    unit_id: number;
    unit_name: string;
  }

  /** 运营概览，对应后端 DashboardOverview */
  export interface Overview {
    confirmed_reconciliations: number;
    deliveries_overdue: number;
    expiry_alerts: null | number;
    inventory_available: boolean;
    inventory_quantity: null | string;
    inventory_units: InventoryUnit[];
    open_exceptions: number;
    paid_amount: string;
    purchase_orders_in_progress: number;
    purchase_orders_total: number;
  }

  /** 采购趋势行 */
  export interface TrendRow {
    date: string;
    order_amount: string;
    order_count: number;
  }

  /** 订单状态分布行 */
  export interface StatusRow {
    order_amount: string;
    order_count: number;
    status: string;
  }

  /** 供应商采购统计行 */
  export interface SupplierRow {
    order_amount: string;
    order_count: number;
    overdue_deliveries: number;
    supplier_id: number;
    supplier_name: string;
  }

  /** 产品出库成本行 */
  export interface CostRow {
    outbound_cost: string;
    outbound_quantity: string;
    product_id: number;
    product_name: string;
  }

  /** 待办任务行 */
  export interface TaskRow {
    task_count: number;
    task_type: string;
  }

  /** 库存有效期预警行 */
  export interface InventoryAlertRow {
    balance_id: number;
    batch_no: string;
    days_remaining: number;
    expiry_date: string;
    level: string;
    location_name: string;
    product_name: string;
    quantity: string;
    unit_name: string;
    warehouse_name: string;
  }

  /** 统计报表，对应后端 DashboardReport */
  export interface Report {
    date_from?: null | string;
    date_to?: null | string;
    inventory_available: boolean;
    inventory_alerts: InventoryAlertRow[];
    inventory_costs: CostRow[];
    order_statuses: StatusRow[];
    order_trend: TrendRow[];
    pending_tasks: TaskRow[];
    supplier_performance: SupplierRow[];
  }
}

/** 查询运营概览指标 */
export async function getDashboardOverviewApi() {
  return requestClient.get<DashboardApi.Overview>('/dashboard/overview');
}

/** 查询统计报表，可按日期范围过滤 */
export async function getDashboardReportApi(params?: {
  date_from?: string;
  date_to?: string;
}) {
  return requestClient.get<DashboardApi.Report>('/dashboard/report', {
    params,
  });
}

/** 服务状态，用于展示数据环境（演示/生产） */
export interface HealthStatus {
  data_mode: string;
  data_source: string;
  environment: string;
  service: string;
  status: string;
}

/** 后端存活检查，注意该接口不带 /api/v1 前缀 */
export async function getHealthApi() {
  return requestClient.get<HealthStatus>('/health', { baseURL: '/' });
}
