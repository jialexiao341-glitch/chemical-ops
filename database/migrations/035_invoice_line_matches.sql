CREATE TABLE IF NOT EXISTS finance_invoice_matches (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    version_no INT NOT NULL,
    reconciliation_version INT NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    allocations JSON NOT NULL,
    note VARCHAR(1000) NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_invoice_match_version (invoice_id, version_no),
    CONSTRAINT fk_invoice_match_invoice FOREIGN KEY (invoice_id) REFERENCES finance_invoices(id),
    CONSTRAINT fk_invoice_match_creator FOREIGN KEY (created_by) REFERENCES sys_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发票人工行匹配历史版本';
