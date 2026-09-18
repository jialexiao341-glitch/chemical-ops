-- ChemicalOps 库存冻结/解冻增量迁移，适用于已经存在的开发数据库。
-- 冻结只改变库存状态，不改变库存数量。

CREATE TABLE IF NOT EXISTS inventory_balance_status_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    balance_id BIGINT UNSIGNED NOT NULL,
    previous_status VARCHAR(20) NOT NULL,
    new_status VARCHAR(20) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    operator_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_inventory_balance_status_log_balance_time (balance_id, created_at),
    KEY idx_inventory_balance_status_log_operator_time (operator_id, created_at),
    CONSTRAINT fk_inventory_balance_status_log_balance FOREIGN KEY (balance_id) REFERENCES inventory_balances (id),
    CONSTRAINT fk_inventory_balance_status_log_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
