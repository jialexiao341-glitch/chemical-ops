-- Preserve historical unknowns and snapshot the tax basis for new orders.
ALTER TABLE purchase_order_items
    ADD COLUMN tax_included TINYINT(1) NULL COMMENT '中选报价单价是否含税，历史口径未知为空' AFTER tax_rate;
