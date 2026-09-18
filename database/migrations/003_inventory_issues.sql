-- ChemicalOps 库存领用和出库增量迁移，适用于已经存在的开发数据库。
-- 执行前请确认当前数据库连接的是 chemicalops。

CREATE TABLE IF NOT EXISTS inventory_issue_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    issue_no VARCHAR(32) NOT NULL,
    applicant_id BIGINT UNSIGNED NOT NULL,
    department_id BIGINT UNSIGNED NULL,
    purpose VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    approved_by BIGINT UNSIGNED NULL,
    approved_at DATETIME(3) NULL,
    rejected_at DATETIME(3) NULL,
    reject_reason VARCHAR(1000) NULL,
    cancelled_at DATETIME(3) NULL,
    completed_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_issue_no (issue_no),
    KEY idx_inventory_issue_applicant_status (applicant_id, status),
    KEY idx_inventory_issue_status_time (status, created_at),
    CONSTRAINT fk_inventory_issue_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_inventory_issue_department FOREIGN KEY (department_id) REFERENCES sys_departments (id),
    CONSTRAINT fk_inventory_issue_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory_issue_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    issue_request_id BIGINT UNSIGNED NOT NULL,
    line_no SMALLINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    warehouse_id BIGINT UNSIGNED NOT NULL,
    location_id BIGINT UNSIGNED NOT NULL,
    batch_id BIGINT UNSIGNED NOT NULL,
    unit_id BIGINT UNSIGNED NOT NULL,
    requested_quantity DECIMAL(18,6) NOT NULL,
    issued_quantity DECIMAL(18,6) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    note VARCHAR(1000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_issue_item_line (issue_request_id, line_no),
    KEY idx_inventory_issue_item_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_issue_item_request FOREIGN KEY (issue_request_id) REFERENCES inventory_issue_requests (id),
    CONSTRAINT fk_inventory_issue_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_issue_item_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_issue_item_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_issue_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_issue_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_issue_item_quantity CHECK (requested_quantity > 0 AND issued_quantity >= 0 AND issued_quantity <= requested_quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
