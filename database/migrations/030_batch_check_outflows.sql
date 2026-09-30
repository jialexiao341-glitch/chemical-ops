ALTER TABLE batch_check_items
    MODIFY COLUMN balance_id BIGINT UNSIGNED NULL,
    ADD COLUMN transaction_id BIGINT UNSIGNED NULL AFTER balance_id,
    ADD COLUMN target_label VARCHAR(255) NOT NULL DEFAULT '' AFTER transaction_id,
    ADD UNIQUE KEY uk_batch_check_transaction (batch_id, transaction_id),
    ADD CONSTRAINT fk_batch_check_transaction FOREIGN KEY (transaction_id) REFERENCES inventory_transactions (id);

UPDATE batch_check_items SET target_label = CONCAT('库存余额 #', balance_id) WHERE target_label = '';
