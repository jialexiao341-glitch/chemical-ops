-- 历史来源不改写。审计表仅记迁移时已存在的重复订单，最小 ID 保留唯一键。
CREATE TABLE IF NOT EXISTS purchase_order_source_exceptions (
    po_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    source_comparison_id BIGINT UNSIGNED NOT NULL,
    canonical_po_id BIGINT UNSIGNED NOT NULL,
    reason VARCHAR(500) NOT NULL,
    recorded_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_po_source_exception_order FOREIGN KEY (po_id) REFERENCES purchase_orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE purchase_orders
    ADD COLUMN legacy_source_duplicate BOOLEAN NOT NULL DEFAULT 0,
    ADD COLUMN source_comparison_guard BIGINT UNSIGNED
        GENERATED ALWAYS AS (CASE WHEN legacy_source_duplicate = 0 THEN source_comparison_id ELSE NULL END) STORED;

INSERT IGNORE INTO purchase_order_source_exceptions
    (po_id, source_comparison_id, canonical_po_id, reason)
SELECT p.id, p.source_comparison_id, d.canonical_po_id,
       '迁移前重复来源，保留业务记录及原始来源；最小订单 ID 占用唯一键，非事实来源裁决'
FROM purchase_orders p
JOIN (SELECT source_comparison_id, MIN(id) canonical_po_id
      FROM purchase_orders WHERE source_comparison_id IS NOT NULL
      GROUP BY source_comparison_id HAVING COUNT(*) > 1) d
ON p.source_comparison_id=d.source_comparison_id AND p.id<>d.canonical_po_id;

UPDATE purchase_orders p JOIN purchase_order_source_exceptions e
ON e.po_id=p.id AND e.source_comparison_id=p.source_comparison_id
SET p.legacy_source_duplicate=1;

ALTER TABLE purchase_orders ADD UNIQUE KEY uk_purchase_order_comparison (source_comparison_guard);
