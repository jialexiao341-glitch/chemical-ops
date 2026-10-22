ALTER TABLE supplier_quote_items
    ADD COLUMN tax_included TINYINT(1) NULL COMMENT '报价单价是否含税；未知时为空' AFTER tax_rate;

ALTER TABLE quote_comparison_items
    MODIFY COLUMN quoted_unit_price DECIMAL(18,6) NULL COMMENT '比较时单价快照；缺失报价明细时为空',
    ADD COLUMN currency_code CHAR(3) NULL COMMENT '比较时币种快照' AFTER total_amount,
    ADD COLUMN unit_id BIGINT UNSIGNED NULL COMMENT '比较时报价单位快照' AFTER currency_code,
    ADD COLUMN tax_rate DECIMAL(5,2) NULL COMMENT '比较时税率快照' AFTER unit_id,
    ADD COLUMN tax_included TINYINT(1) NULL COMMENT '比较时含税口径快照' AFTER tax_rate,
    ADD COLUMN comparison_status VARCHAR(20) NOT NULL DEFAULT 'NOT_COMPARABLE' COMMENT '口径比较状态' AFTER tax_included,
    ADD COLUMN comparison_reasons JSON NULL COMMENT '不可比原因' AFTER comparison_status;

UPDATE quote_comparison_items
SET rank_no = NULL,
    comparison_status = 'NOT_COMPARABLE',
    comparison_reasons = JSON_ARRAY('旧版比价结果未保存报价口径，请重新生成');

UPDATE quote_comparison_items AS comparison_item
JOIN quote_comparisons AS comparison ON comparison.id = comparison_item.comparison_id
SET comparison_item.selection_flag = 0
WHERE comparison.status <> 'CONFIRMED';
