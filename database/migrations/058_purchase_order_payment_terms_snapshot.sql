-- Keep the selected quote's per-line payment terms as an order-time snapshot.
-- Existing orders remain NULL because their historical terms were not captured.
ALTER TABLE purchase_order_items
    ADD COLUMN payment_terms_snapshot VARCHAR(255) NULL COMMENT '中选报价付款条件原文快照' AFTER tax_rate;
