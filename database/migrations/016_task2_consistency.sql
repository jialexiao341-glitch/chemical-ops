-- 任务块二：异常未关闭去重和一到货单一验收约束。
-- 同来源、同类型的重复异常保留最早创建的一条，其余关闭；任务取消但保留任务和评论作为审计记录。
DROP TEMPORARY TABLE IF EXISTS migration_016_duplicate_exceptions;
CREATE TEMPORARY TABLE migration_016_duplicate_exceptions AS
SELECT exception_type, source_type, source_id, MIN(id) AS canonical_id
FROM operation_exceptions
WHERE status IN ('OPEN', 'PROCESSING', 'RESOLVED')
GROUP BY exception_type, source_type, source_id
HAVING COUNT(*) > 1;

UPDATE operation_tasks t
JOIN operation_exceptions duplicate_exception ON duplicate_exception.id = t.exception_id
JOIN migration_016_duplicate_exceptions duplicates
    ON duplicates.exception_type = duplicate_exception.exception_type
    AND duplicates.source_type = duplicate_exception.source_type
    AND duplicates.source_id = duplicate_exception.source_id
JOIN operation_exceptions canonical_exception ON canonical_exception.id = duplicates.canonical_id
SET t.status = 'CANCELLED',
    t.completion_note = LEFT(CONCAT_WS('\n', NULLIF(t.completion_note, ''),
        CONCAT('迁移自动关闭重复异常任务；保留异常 ', canonical_exception.exception_no,
            ' (ID=', canonical_exception.id, ')')), 2000)
WHERE duplicate_exception.id <> duplicates.canonical_id
    AND t.status IN ('OPEN', 'PROCESSING');

UPDATE operation_exceptions duplicate_exception
JOIN migration_016_duplicate_exceptions duplicates
    ON duplicates.exception_type = duplicate_exception.exception_type
    AND duplicates.source_type = duplicate_exception.source_type
    AND duplicates.source_id = duplicate_exception.source_id
JOIN operation_exceptions canonical_exception ON canonical_exception.id = duplicates.canonical_id
SET duplicate_exception.status = 'CLOSED',
    duplicate_exception.closed_at = COALESCE(duplicate_exception.closed_at, CURRENT_TIMESTAMP(3)),
    duplicate_exception.closing_note = LEFT(CONCAT_WS('\n',
        NULLIF(duplicate_exception.closing_note, ''),
        CONCAT('迁移自动关闭重复异常；保留异常 ', canonical_exception.exception_no,
            ' (ID=', canonical_exception.id, ')')), 2000)
WHERE duplicate_exception.id <> duplicates.canonical_id;

DROP TEMPORARY TABLE migration_016_duplicate_exceptions;

ALTER TABLE operation_exceptions
    ADD COLUMN active_dedupe_key VARCHAR(200)
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN ('OPEN', 'PROCESSING', 'RESOLVED')
                THEN CONCAT(exception_type, ':', source_type, ':', source_id)
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uk_exception_active_dedupe (active_dedupe_key);

ALTER TABLE quality_acceptances
    ADD UNIQUE KEY uk_acceptance_delivery (delivery_id);
