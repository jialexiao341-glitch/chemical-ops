-- ChemicalOps 库存模块增量迁移，适用于已存在的开发数据库。
-- 执行前请确认当前数据库连接的是 chemicalops。

CREATE TABLE IF NOT EXISTS warehouses (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    warehouse_code VARCHAR(64) NOT NULL,
    warehouse_name VARCHAR(128) NOT NULL,
    region VARCHAR(128) NULL,
    address VARCHAR(500) NULL,
    manager_id BIGINT UNSIGNED NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    note VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_warehouse_code (warehouse_code),
    KEY idx_warehouse_status_name (status, warehouse_name),
    CONSTRAINT fk_warehouse_manager FOREIGN KEY (manager_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS warehouse_locations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    warehouse_id BIGINT UNSIGNED NOT NULL,
    location_code VARCHAR(64) NOT NULL,
    location_name VARCHAR(128) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    note VARCHAR(500) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_location_warehouse_code (warehouse_id, location_code),
    KEY idx_location_warehouse_status (warehouse_id, status),
    CONSTRAINT fk_location_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory_batches (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id BIGINT UNSIGNED NOT NULL,
    batch_no VARCHAR(128) NOT NULL,
    supplier_id BIGINT UNSIGNED NULL,
    source_delivery_id BIGINT UNSIGNED NULL,
    production_date DATE NULL,
    expiry_date DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    note VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_batch_source (product_id, batch_no, source_delivery_id),
    KEY idx_inventory_batch_expiry (product_id, expiry_date, status),
    CONSTRAINT fk_inventory_batch_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_batch_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_inventory_batch_delivery FOREIGN KEY (source_delivery_id) REFERENCES deliveries (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory_balances (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    warehouse_id BIGINT UNSIGNED NOT NULL,
    location_id BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    batch_id BIGINT UNSIGNED NOT NULL,
    unit_id BIGINT UNSIGNED NOT NULL,
    quantity DECIMAL(18,6) NOT NULL DEFAULT 0,
    locked_quantity DECIMAL(18,6) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_balance_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    KEY idx_inventory_balance_product (product_id, warehouse_id, status),
    CONSTRAINT fk_inventory_balance_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_balance_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_balance_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_balance_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_balance_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_balance_quantity CHECK (quantity >= 0 AND locked_quantity >= 0 AND locked_quantity <= quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    transaction_no VARCHAR(32) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    warehouse_id BIGINT UNSIGNED NOT NULL,
    location_id BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    batch_id BIGINT UNSIGNED NOT NULL,
    unit_id BIGINT UNSIGNED NOT NULL,
    quantity DECIMAL(18,6) NOT NULL,
    delivery_item_id BIGINT UNSIGNED NULL,
    source_type VARCHAR(32) NULL,
    source_id BIGINT UNSIGNED NULL,
    operator_id BIGINT UNSIGNED NOT NULL,
    note VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_transaction_no (transaction_no),
    UNIQUE KEY uk_inventory_transaction_delivery_item (delivery_item_id),
    KEY idx_inventory_transaction_product_time (product_id, created_at),
    CONSTRAINT fk_inventory_transaction_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_transaction_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_transaction_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_transaction_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_transaction_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT fk_inventory_transaction_delivery_item FOREIGN KEY (delivery_item_id) REFERENCES delivery_items (id),
    CONSTRAINT fk_inventory_transaction_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id),
    CONSTRAINT chk_inventory_transaction_quantity CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
