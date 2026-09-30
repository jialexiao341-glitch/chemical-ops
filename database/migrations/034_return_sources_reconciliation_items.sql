ALTER TABLE inventory_return_items
    ADD COLUMN source_delivery_item_id BIGINT UNSIGNED NULL,
    ADD COLUMN source_po_item_id BIGINT UNSIGNED NULL,
    ADD KEY idx_return_source_delivery_item (source_delivery_item_id),
    ADD KEY idx_return_source_po_item (source_po_item_id),
    ADD CONSTRAINT fk_return_source_delivery_item FOREIGN KEY (source_delivery_item_id) REFERENCES delivery_items(id),
    ADD CONSTRAINT fk_return_source_po_item FOREIGN KEY (source_po_item_id) REFERENCES purchase_order_items(id);

ALTER TABLE finance_reconciliations
    ADD COLUMN items_version INT NOT NULL DEFAULT 0,
    ADD COLUMN source_hash VARCHAR(64) NULL,
    ADD COLUMN amount_precision INT NOT NULL DEFAULT 2,
    DROP CHECK chk_finance_reconciliation_amount,
    ADD CONSTRAINT chk_finance_reconciliation_amount CHECK (total_amount >= 0);

ALTER TABLE finance_settlements
    DROP CHECK chk_finance_settlement_amount,
    ADD CONSTRAINT chk_finance_settlement_amount CHECK (settlement_amount >= 0);

CREATE TABLE IF NOT EXISTS finance_reconciliation_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    reconciliation_id BIGINT UNSIGNED NOT NULL,
    version_no INT NOT NULL,
    po_item_id BIGINT UNSIGNED NOT NULL,
    line_no INT NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    unit_name VARCHAR(64) NOT NULL,
    ordered_quantity DECIMAL(18,6) NOT NULL,
    received_quantity DECIMAL(18,6) NOT NULL,
    accepted_quantity DECIMAL(18,6) NOT NULL,
    returned_quantity DECIMAL(18,6) NOT NULL,
    reconciliation_quantity DECIMAL(18,6) NOT NULL,
    unit_price DECIMAL(18,6) NOT NULL,
    tax_rate DECIMAL(5,2) NOT NULL,
    amount_excl_tax DECIMAL(18,6) NOT NULL,
    tax_amount DECIMAL(18,6) NOT NULL,
    amount_incl_tax DECIMAL(18,6) NOT NULL,
    return_treatment VARCHAR(20) NOT NULL,
    treatment_note VARCHAR(1000) NULL,
    basis_json JSON NOT NULL,
    warnings JSON NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_finance_rec_item_version (reconciliation_id, version_no, po_item_id),
    CONSTRAINT fk_rec_item_reconciliation FOREIGN KEY (reconciliation_id) REFERENCES finance_reconciliations(id),
    CONSTRAINT fk_rec_item_po_item FOREIGN KEY (po_item_id) REFERENCES purchase_order_items(id),
    CONSTRAINT fk_rec_item_creator FOREIGN KEY (created_by) REFERENCES sys_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='按版本保留的订单行对账依据';
