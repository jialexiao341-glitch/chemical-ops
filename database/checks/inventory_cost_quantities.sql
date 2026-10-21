-- 只读对账：覆盖无余额但仍有成本层、无成本层但仍有余额的双向差异。
WITH slots AS (
    SELECT warehouse_id, location_id, product_id, batch_id, unit_id, quantity, 0 AS cost_quantity
    FROM inventory_balances
    UNION ALL
    SELECT warehouse_id, location_id, product_id, batch_id, unit_id, 0 AS quantity, remaining_quantity AS cost_quantity
    FROM inventory_cost_layers
)
SELECT warehouse_id, location_id, product_id, batch_id, unit_id,
       SUM(quantity) AS balance_quantity, SUM(cost_quantity) AS cost_quantity,
       SUM(quantity) - SUM(cost_quantity) AS difference
FROM slots
GROUP BY warehouse_id, location_id, product_id, batch_id, unit_id
HAVING SUM(quantity) <> SUM(cost_quantity);
