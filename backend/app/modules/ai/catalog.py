"""Text2SQL 的数据集、表、字段、指标和权限白名单。

这里是唯一允许进入查询规划和 SQL 生成阶段的业务元数据入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    permission: str
    tables: frozenset[str]
    metrics: frozenset[str]
    dimensions: frozenset[str]
    filters: frozenset[str]
    times: frozenset[str]


CATALOG: dict[str, DatasetSpec] = {
    "approved_requests_without_rfq": DatasetSpec("已审批未建立询价单的采购申请", "procurement.requests.read", frozenset({"purchase_requests", "purchase_request_items", "rfq_items", "rfqs"}), frozenset({"records"}), frozenset(), frozenset(), frozenset()),
    "weekly_order_risks": DatasetSpec("本周订单履约风险", "procurement.orders.read", frozenset({"purchase_orders", "purchase_order_items", "suppliers", "deliveries", "delivery_items", "md_units"}), frozenset({"records"}), frozenset(), frozenset(), frozenset()),
    "inventory_by_batch": DatasetSpec("产品批次可用库存", "warehouse.inventory.read", frozenset({"inventory_balances", "inventory_batches", "md_products", "warehouses", "md_units"}), frozenset({"records"}), frozenset(), frozenset({"product_id"}), frozenset()),
    "accepted_orders_finance_gaps": DatasetSpec("已验收订单财务进度", "finance.reconciliations.read", frozenset({"purchase_orders", "suppliers", "deliveries", "finance_reconciliations", "finance_invoices", "finance_payments", "finance_settlements"}), frozenset({"records"}), frozenset(), frozenset(), frozenset()),
    "supplier_quote_delivery_profile": DatasetSpec("供应商报价、交期与异常表现", "master.suppliers.read", frozenset({"suppliers", "supplier_products", "md_products", "md_units", "chemicals", "rfqs", "rfq_items", "supplier_quotes", "supplier_quote_items", "purchase_orders", "purchase_order_items", "deliveries", "delivery_items", "operation_exceptions"}), frozenset({"records"}), frozenset(), frozenset({"supplier_id", "product_id"}), frozenset()),
    "inventory_movement_trace": DatasetSpec("库存变动与冻结原因追溯", "warehouse.inventory.read", frozenset({"inventory_transactions", "inventory_balance_status_logs", "inventory_balances", "inventory_batches", "md_products", "warehouses", "warehouse_locations", "md_units", "chemicals"}), frozenset({"records"}), frozenset(), frozenset({"product_id", "batch_id"}), frozenset()),
    "purchase_requests": DatasetSpec("采购申请", "procurement.requests.read", frozenset({"purchase_requests"}), frozenset({"count", "amount"}), frozenset({"status", "priority", "currency"}), frozenset({"status", "priority", "currency_code"}), frozenset({"created_at", "expected_date", "submitted_at", "approved_at"})),
    "purchase_orders": DatasetSpec("采购订单", "procurement.orders.read", frozenset({"purchase_orders", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "region", "status", "currency"}), frozenset({"status", "supplier_name", "region", "currency_code"}), frozenset({"created_at", "order_date", "expected_arrival_date"})),
    "deliveries": DatasetSpec("入库单", "warehouse.deliveries.read", frozenset({"deliveries", "suppliers"}), frozenset({"count"}), frozenset({"supplier", "status"}), frozenset({"status", "supplier_name"}), frozenset({"created_at", "expected_arrival_date", "actual_arrival_date"})),
    "inventory": DatasetSpec("库存", "warehouse.inventory.read", frozenset({"inventory_balances", "inventory_batches", "md_products", "warehouses"}), frozenset({"sum_quantity", "count"}), frozenset({"product", "warehouse", "status", "expiry_date"}), frozenset({"product_name", "warehouse_name", "status"}), frozenset({"created_at", "expiry_date"})),
    "quality_acceptances": DatasetSpec("质量验收", "quality.acceptances.read", frozenset({"quality_acceptances", "deliveries"}), frozenset({"count"}), frozenset({"result", "certificate_complete"}), frozenset({"result", "certificate_complete"}), frozenset({"created_at", "inspection_time"})),
    "exceptions": DatasetSpec("运营异常", "operations.exceptions.read", frozenset({"operation_exceptions"}), frozenset({"count"}), frozenset({"type", "severity", "status"}), frozenset({"type", "severity", "status"}), frozenset({"created_at", "due_at"})),
    "finance_reconciliations": DatasetSpec("财务对账", "finance.reconciliations.read", frozenset({"finance_reconciliations", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at"})),
    "supplier_quotes": DatasetSpec("供应商报价", "procurement.rfqs.read", frozenset({"supplier_quotes", "rfqs", "suppliers"}), frozenset({"count"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at", "quote_date"})),
    "inventory_transactions": DatasetSpec("库存流水", "warehouse.inventory.read", frozenset({"inventory_transactions", "md_products", "warehouses"}), frozenset({"count"}), frozenset({"type", "product", "warehouse"}), frozenset({"type", "product_name", "warehouse_name"}), frozenset({"created_at"})),
    "finance_invoices": DatasetSpec("财务发票", "finance.invoices.read", frozenset({"finance_invoices", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at", "invoice_date", "verified_at"})),
    "finance_payments": DatasetSpec("财务付款", "finance.payments.read", frozenset({"finance_payments", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at", "approved_at", "paid_at"})),
    "suppliers": DatasetSpec("供应商", "master.suppliers.read", frozenset({"suppliers"}), frozenset({"count"}), frozenset({"region", "cooperation_level", "status"}), frozenset({"region", "cooperation_level", "status"}), frozenset({"created_at"})),
}


def catalog_prompt() -> str:
    """生成给模型看的最小白名单，不包含数据库中未开放的字段。"""

    return json.dumps(
        {
            key: {
                "label": spec.label,
                "metrics": sorted(spec.metrics),
                "dimensions": sorted(spec.dimensions),
                "filters": sorted(spec.filters),
                "times": sorted(spec.times),
            }
            for key, spec in CATALOG.items()
            if key not in {"approved_requests_without_rfq", "weekly_order_risks", "inventory_by_batch", "accepted_orders_finance_gaps", "supplier_quote_delivery_profile", "inventory_movement_trace"}
        },
        ensure_ascii=False,
    )
