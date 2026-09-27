ALTER TABLE md_products
    ADD COLUMN safety_stock_quantity DECIMAL(18,6) NULL COMMENT '安全库存阈值，单位沿用产品计量单位' AFTER unit_id,
    ADD KEY idx_product_safety_stock (status, safety_stock_quantity);
