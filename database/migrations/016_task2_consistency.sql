-- 任务块二：异常未关闭去重和一到货单一验收约束。
-- 执行前应确认 operation_exceptions 中不存在同来源、同类型的多个未关闭异常。
ALTER TABLE operation_exceptions
    ADD COLUMN active_dedupe_key VARCHAR(200)
        GENERATED ALWAYS (
            CASE
                WHEN status IN ('OPEN', 'PROCESSING', 'RESOLVED')
                THEN CONCAT(exception_type, ':', source_type, ':', source_id)
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uk_exception_active_dedupe (active_dedupe_key);

ALTER TABLE quality_acceptances
    ADD UNIQUE KEY uk_acceptance_delivery (delivery_id);