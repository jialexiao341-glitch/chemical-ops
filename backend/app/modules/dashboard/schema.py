"""Dashboard 统计响应模型。"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class DashboardInventoryUnit(BaseModel):
    """Dashboard 库存按计量单位拆分的统计行。"""

    unit_id: int
    unit_code: str
    unit_name: str
    quantity: Decimal


class DashboardOverview(BaseModel):
    """采购、库存、异常和财务核心指标。"""
    purchase_orders_total: int
    purchase_orders_in_progress: int
    deliveries_overdue: int
    inventory_quantity: Decimal
    inventory_units: list[DashboardInventoryUnit]
    open_exceptions: int
    confirmed_reconciliations: int
    paid_amount: Decimal
    expiry_alerts: int


class DashboardStatusRow(BaseModel):
    """采购订单状态统计行。"""
    status: str
    order_count: int
    order_amount: Decimal


class DashboardTrendRow(BaseModel):
    """采购订单按日期聚合的趋势行。"""

    date: date
    order_count: int
    order_amount: Decimal


class DashboardSupplierRow(BaseModel):
    """供应商采购与逾期统计行。"""
    supplier_id: int
    supplier_name: str
    order_count: int
    order_amount: Decimal
    overdue_deliveries: int


class DashboardCostRow(BaseModel):
    """库存出库成本统计行。"""
    product_id: int
    product_name: str
    outbound_quantity: Decimal
    outbound_cost: Decimal


class DashboardTaskRow(BaseModel):
    """首页待办聚合行，数量必须来自业务表。"""

    task_type: str
    task_count: int


class DashboardInventoryAlertRow(BaseModel):
    """首页库存有效期预警行。"""

    balance_id: int
    product_name: str
    batch_no: str
    warehouse_name: str
    location_name: str
    quantity: Decimal
    unit_name: str
    expiry_date: date
    days_remaining: int
    level: str


class DashboardReport(BaseModel):
    """按时间范围返回采购订单和供应商统计报表。"""
    date_from: date | None
    date_to: date | None
    order_trend: list[DashboardTrendRow]
    order_statuses: list[DashboardStatusRow]
    supplier_performance: list[DashboardSupplierRow]
    inventory_costs: list[DashboardCostRow]
    pending_tasks: list[DashboardTaskRow]
    inventory_alerts: list[DashboardInventoryAlertRow]
