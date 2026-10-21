-- 取消的结算单保留审计历史，同一对账单最多一张未取消结算单。
ALTER TABLE finance_settlements
    ADD COLUMN active_reconciliation_id BIGINT UNSIGNED
        GENERATED ALWAYS AS (CASE WHEN status <> 'CANCELLED' THEN reconciliation_id ELSE NULL END) STORED,
    ADD KEY idx_finance_settlement_reconciliation (reconciliation_id),
    DROP INDEX uk_finance_settlement_reconciliation,
    ADD UNIQUE KEY uk_finance_settlement_reconciliation (active_reconciliation_id);
