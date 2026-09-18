-- ChemicalOps 退货和补货申请增量迁移。

CREATE TABLE IF NOT EXISTS inventory_return_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    return_no VARCHAR(32) NOT NULL COMMENT '退货单业务编号',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '退回供应商 ID',
    po_id BIGINT UNSIGNED NULL COMMENT '来源采购订单 ID',
    delivery_id BIGINT UNSIGNED NULL COMMENT '来源到货单 ID',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID',
    reason VARCHAR(1000) NOT NULL COMMENT '退货原因',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID',
    approved_at DATETIME(3) NULL COMMENT '审批时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间',
    reject_reason VARCHAR(1000) NULL COMMENT '驳回原因',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    completed_at DATETIME(3) NULL COMMENT '完成时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_return_no (return_no),
    KEY idx_inventory_return_supplier_status (supplier_id, status), KEY idx_inventory_return_source (po_id, delivery_id),
    CONSTRAINT fk_inventory_return_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_inventory_return_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_inventory_return_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries (id), CONSTRAINT fk_inventory_return_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_inventory_return_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供应商退货申请';

CREATE TABLE IF NOT EXISTS inventory_return_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', return_request_id BIGINT UNSIGNED NOT NULL COMMENT '退货申请 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号', product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID',
    location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '库存批次 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID',
    requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请退货数量', returned_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际退货数量', status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、RETURNED', note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_return_item_line (return_request_id, line_no), KEY idx_inventory_return_item_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_return_item_request FOREIGN KEY (return_request_id) REFERENCES inventory_return_requests (id), CONSTRAINT fk_inventory_return_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_return_item_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_return_item_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_return_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT fk_inventory_return_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_return_item_quantity CHECK (requested_quantity > 0 AND returned_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供应商退货明细';

CREATE TABLE IF NOT EXISTS replenishment_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', replenishment_no VARCHAR(32) NOT NULL COMMENT '补货申请业务编号',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '补货供应商 ID', source_po_id BIGINT UNSIGNED NULL COMMENT '来源采购订单 ID', source_delivery_id BIGINT UNSIGNED NULL COMMENT '来源到货单 ID',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID', reason VARCHAR(1000) NOT NULL COMMENT '补货原因', status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED',
    fulfillment_po_id BIGINT UNSIGNED NULL COMMENT '实际执行补货的采购订单 ID', approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID', approved_at DATETIME(3) NULL COMMENT '审批时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间', reject_reason VARCHAR(1000) NULL COMMENT '驳回原因', cancelled_at DATETIME(3) NULL COMMENT '取消时间', completed_at DATETIME(3) NULL COMMENT '完成时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_replenishment_no (replenishment_no), KEY idx_replenishment_supplier_status (supplier_id, status), KEY idx_replenishment_source (source_po_id, source_delivery_id),
    CONSTRAINT fk_replenishment_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_replenishment_source_po FOREIGN KEY (source_po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_replenishment_source_delivery FOREIGN KEY (source_delivery_id) REFERENCES deliveries (id), CONSTRAINT fk_replenishment_fulfillment_po FOREIGN KEY (fulfillment_po_id) REFERENCES purchase_orders (id), CONSTRAINT fk_replenishment_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id), CONSTRAINT fk_replenishment_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供应商补货申请';

CREATE TABLE IF NOT EXISTS replenishment_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', replenishment_request_id BIGINT UNSIGNED NOT NULL COMMENT '补货申请 ID', line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID', requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请补货数量', expected_date DATE NULL COMMENT '期望到货日期', status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、FULFILLED', note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_replenishment_item_line (replenishment_request_id, line_no), KEY idx_replenishment_item_product (product_id, status),
    CONSTRAINT fk_replenishment_item_request FOREIGN KEY (replenishment_request_id) REFERENCES replenishment_requests (id), CONSTRAINT fk_replenishment_item_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_replenishment_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_replenishment_item_quantity CHECK (requested_quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供应商补货明细';
