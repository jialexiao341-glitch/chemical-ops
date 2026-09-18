-- ChemicalOps 库存成本层、FIFO 出库和有效期预警增量迁移。

CREATE TABLE IF NOT EXISTS inventory_cost_layers (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    source_transaction_id BIGINT UNSIGNED NOT NULL COMMENT '来源入库流水 ID',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID', location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID',
    unit_cost DECIMAL(18,6) NOT NULL COMMENT '单位成本', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '成本币种',
    original_quantity DECIMAL(18,6) NOT NULL COMMENT '成本层原始数量', remaining_quantity DECIMAL(18,6) NOT NULL COMMENT '成本层剩余数量',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '成本层创建时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_cost_layer_source (source_transaction_id),
    KEY idx_inventory_cost_layer_fifo (product_id, warehouse_id, location_id, unit_id, remaining_quantity, created_at),
    KEY idx_inventory_cost_layer_expiry (batch_id, remaining_quantity),
    CONSTRAINT fk_inventory_cost_layer_transaction FOREIGN KEY (source_transaction_id) REFERENCES inventory_transactions (id),
    CONSTRAINT fk_inventory_cost_layer_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_cost_layer_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_cost_layer_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_inventory_cost_layer_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT fk_inventory_cost_layer_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_cost_layer_quantity CHECK (original_quantity > 0 AND remaining_quantity >= 0 AND remaining_quantity <= original_quantity), CONSTRAINT chk_inventory_cost_layer_cost CHECK (unit_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='库存 FIFO 成本层';

CREATE TABLE IF NOT EXISTS inventory_fifo_outbound_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', request_no VARCHAR(64) NOT NULL COMMENT '客户端幂等请求号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID', location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID',
    requested_quantity DECIMAL(18,6) NOT NULL COMMENT '请求出库数量', issued_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际出库数量', total_cost DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT 'FIFO 汇总成本', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '成本币种',
    status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED' COMMENT 'COMPLETED', operator_id BIGINT UNSIGNED NOT NULL COMMENT '操作人用户 ID', note VARCHAR(1000) NULL COMMENT '备注', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_fifo_request_no (request_no), KEY idx_inventory_fifo_request_product_time (product_id, warehouse_id, location_id, created_at),
    CONSTRAINT fk_inventory_fifo_request_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_inventory_fifo_request_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_fifo_request_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id), CONSTRAINT fk_inventory_fifo_request_unit FOREIGN KEY (unit_id) REFERENCES md_units (id), CONSTRAINT fk_inventory_fifo_request_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id), CONSTRAINT chk_inventory_fifo_request_quantity CHECK (requested_quantity > 0 AND issued_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='FIFO 出库请求';

CREATE TABLE IF NOT EXISTS inventory_fifo_outbound_allocations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', request_id BIGINT UNSIGNED NOT NULL COMMENT 'FIFO 出库请求 ID', cost_layer_id BIGINT UNSIGNED NOT NULL COMMENT '成本层 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID', quantity DECIMAL(18,6) NOT NULL COMMENT '本层分摊数量', unit_cost DECIMAL(18,6) NOT NULL COMMENT '本层单位成本', total_cost DECIMAL(18,6) NOT NULL COMMENT '本层成本',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_fifo_allocation_layer (request_id, cost_layer_id), KEY idx_inventory_fifo_allocation_batch (batch_id, request_id),
    CONSTRAINT fk_inventory_fifo_allocation_request FOREIGN KEY (request_id) REFERENCES inventory_fifo_outbound_requests (id), CONSTRAINT fk_inventory_fifo_allocation_layer FOREIGN KEY (cost_layer_id) REFERENCES inventory_cost_layers (id), CONSTRAINT fk_inventory_fifo_allocation_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT chk_inventory_fifo_allocation_quantity CHECK (quantity > 0 AND unit_cost >= 0 AND total_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='FIFO 出库成本分摊';
