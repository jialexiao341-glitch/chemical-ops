-- ChemicalOps 普通库存出库成本分摊增量迁移。

CREATE TABLE IF NOT EXISTS inventory_cost_allocations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    transaction_id BIGINT UNSIGNED NOT NULL COMMENT '库存流水 ID',
    cost_layer_id BIGINT UNSIGNED NOT NULL COMMENT '来源成本层 ID',
    quantity DECIMAL(18,6) NOT NULL COMMENT '分摊数量',
    unit_cost DECIMAL(18,6) NOT NULL COMMENT '单位成本',
    total_cost DECIMAL(18,6) NOT NULL COMMENT '分摊总成本',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_cost_allocation_layer (transaction_id, cost_layer_id),
    KEY idx_inventory_cost_allocation_layer (cost_layer_id, created_at),
    CONSTRAINT fk_inventory_cost_allocation_transaction FOREIGN KEY (transaction_id) REFERENCES inventory_transactions (id),
    CONSTRAINT fk_inventory_cost_allocation_layer FOREIGN KEY (cost_layer_id) REFERENCES inventory_cost_layers (id),
    CONSTRAINT chk_inventory_cost_allocation_amount CHECK (quantity > 0 AND unit_cost >= 0 AND total_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='普通库存出库成本分摊';
