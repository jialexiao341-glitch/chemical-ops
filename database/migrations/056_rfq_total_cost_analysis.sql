ALTER TABLE supplier_quote_items
    ADD COLUMN freight_amount DECIMAL(18,6) NULL COMMENT '报价明细运费金额；未知时为空' AFTER moq_unit_id,
    ADD COLUMN freight_tax_rate DECIMAL(5,2) NULL COMMENT '运费税率百分比；未知时为空' AFTER freight_amount,
    ADD COLUMN freight_tax_included TINYINT(1) NULL COMMENT '运费是否含税；未知时为空' AFTER freight_tax_rate,
    ADD CONSTRAINT chk_quote_item_freight CHECK (
        (freight_amount IS NULL OR freight_amount >= 0)
        AND (freight_tax_rate IS NULL OR freight_tax_rate BETWEEN 0 AND 100)
    );

ALTER TABLE quote_comparison_items
    ADD COLUMN freight_amount DECIMAL(18,6) NULL COMMENT '比较时运费快照' AFTER payment_terms,
    ADD COLUMN freight_tax_rate DECIMAL(5,2) NULL COMMENT '比较时运费税率快照' AFTER freight_amount,
    ADD COLUMN freight_tax_included TINYINT(1) NULL COMMENT '比较时运费含税口径快照' AFTER freight_tax_rate,
    ADD COLUMN analysis_json JSON NULL COMMENT '确定性总成本拆分快照' AFTER freight_tax_included;
