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
    "purchase_orders": DatasetSpec("采购订单", "procurement.orders.read", frozenset({"purchase_orders", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at", "order_date", "expected_arrival_date"})),
    "deliveries": DatasetSpec("入库单", "warehouse.deliveries.read", frozenset({"deliveries", "suppliers"}), frozenset({"count"}), frozenset({"supplier", "status"}), frozenset({"status", "supplier_name"}), frozenset({"created_at", "expected_arrival_date", "actual_arrival_date"})),
    "inventory": DatasetSpec("库存", "warehouse.inventory.read", frozenset({"inventory_balances", "inventory_batches", "md_products", "warehouses"}), frozenset({"sum_quantity", "count"}), frozenset({"product", "warehouse", "status", "expiry_date"}), frozenset({"product_name", "warehouse_name", "status"}), frozenset({"created_at", "expiry_date"})),
    "quality_acceptances": DatasetSpec("质量验收", "quality.acceptances.read", frozenset({"quality_acceptances", "deliveries"}), frozenset({"count"}), frozenset({"result", "certificate_complete"}), frozenset({"result", "certificate_complete"}), frozenset({"created_at", "inspection_time"})),
    "exceptions": DatasetSpec("运营异常", "operations.exceptions.read", frozenset({"operation_exceptions"}), frozenset({"count"}), frozenset({"type", "severity", "status"}), frozenset({"type", "severity", "status"}), frozenset({"created_at", "due_at"})),
    "finance_reconciliations": DatasetSpec("财务对账", "finance.reconciliations.read", frozenset({"finance_reconciliations", "suppliers"}), frozenset({"count", "amount"}), frozenset({"supplier", "status", "currency"}), frozenset({"status", "supplier_name", "currency_code"}), frozenset({"created_at"})),
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
        },
        ensure_ascii=False,
    )
