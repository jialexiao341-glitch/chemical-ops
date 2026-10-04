CREATE TABLE IF NOT EXISTS supplier_delivery_updates (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    po_id BIGINT UNSIGNED NOT NULL,
    supplier_id BIGINT UNSIGNED NOT NULL,
    previous_date DATE NULL,
    expected_date DATE NOT NULL,
    note VARCHAR(1000) NULL,
    submitted_by BIGINT UNSIGNED NOT NULL,
    submitted_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_supplier_delivery_updates_supplier_time (supplier_id, submitted_at),
    KEY idx_supplier_delivery_updates_order (po_id, id),
    CONSTRAINT fk_supplier_delivery_updates_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_supplier_delivery_updates_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_supplier_delivery_updates_user FOREIGN KEY (submitted_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS supplier_quality_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    document_no VARCHAR(32) NOT NULL,
    supplier_id BIGINT UNSIGNED NOT NULL,
    po_id BIGINT UNSIGNED NOT NULL,
    po_item_id BIGINT UNSIGNED NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    document_type VARCHAR(32) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SUBMITTED',
    note VARCHAR(1000) NULL,
    submitted_by BIGINT UNSIGNED NOT NULL,
    submitted_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    reviewed_by BIGINT UNSIGNED NULL,
    reviewed_at DATETIME(3) NULL,
    review_note VARCHAR(1000) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_supplier_quality_documents_no (document_no),
    KEY idx_supplier_quality_documents_supplier_time (supplier_id, submitted_at),
    KEY idx_supplier_quality_documents_order (po_id, id),
    CONSTRAINT fk_supplier_quality_documents_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_supplier_quality_documents_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_supplier_quality_documents_item FOREIGN KEY (po_item_id) REFERENCES purchase_order_items (id),
    CONSTRAINT fk_supplier_quality_documents_file FOREIGN KEY (file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_supplier_quality_documents_submitter FOREIGN KEY (submitted_by) REFERENCES sys_users (id),
    CONSTRAINT fk_supplier_quality_documents_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS supplier_reconciliation_messages (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reconciliation_id BIGINT UNSIGNED NOT NULL,
    supplier_id BIGINT UNSIGNED NOT NULL,
    author_id BIGINT UNSIGNED NOT NULL,
    author_type VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_supplier_rec_messages_reconciliation (reconciliation_id, id),
    KEY idx_supplier_rec_messages_supplier_time (supplier_id, created_at),
    CONSTRAINT fk_supplier_rec_messages_reconciliation FOREIGN KEY (reconciliation_id) REFERENCES finance_reconciliations (id),
    CONSTRAINT fk_supplier_rec_messages_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_supplier_rec_messages_author FOREIGN KEY (author_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES
    ('supplier.portal.delivery.read', '查询供应商交期更新', 'API', 'supplier.portal.delivery', 'read'),
    ('supplier.portal.delivery.update', '更新供应商预计交期', 'API', 'supplier.portal.delivery', 'update'),
    ('supplier.portal.shipment.read', '查询供应商发货通知', 'API', 'supplier.portal.shipment', 'read'),
    ('supplier.portal.shipment.submit', '提交供应商发货通知', 'API', 'supplier.portal.shipment', 'submit'),
    ('supplier.portal.quality.read', '查询供应商质量资料', 'API', 'supplier.portal.quality', 'read'),
    ('supplier.portal.quality.submit', '提交供应商质量资料', 'API', 'supplier.portal.quality', 'submit'),
    ('supplier.portal.reconciliation.read', '查询供应商对账记录', 'API', 'supplier.portal.reconciliation', 'read'),
    ('supplier.portal.reconciliation.respond', '确认或争议供应商对账', 'API', 'supplier.portal.reconciliation', 'respond'),
    ('supplier.portal.reconciliation.message', '提交供应商对账留言', 'API', 'supplier.portal.reconciliation', 'message');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'SUPPLIER_PORTAL'
  AND permission.permission_code IN (
      'supplier.portal.delivery.read', 'supplier.portal.delivery.update',
      'supplier.portal.shipment.read', 'supplier.portal.shipment.submit',
      'supplier.portal.quality.read', 'supplier.portal.quality.submit',
      'supplier.portal.reconciliation.read', 'supplier.portal.reconciliation.respond',
      'supplier.portal.reconciliation.message'
  );
