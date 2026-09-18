-- ChemicalOps 付款银行流水号并发唯一性增量迁移。

ALTER TABLE finance_payments
    ADD UNIQUE KEY uk_finance_payment_transaction_ref (transaction_ref);
