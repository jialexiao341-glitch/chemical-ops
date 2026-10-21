-- 已存在重复来源订单时唯一索引会拒绝迁移，必须先人工核对，不自动删除业务数据。
ALTER TABLE purchase_orders
    ADD UNIQUE KEY uk_purchase_order_comparison (source_comparison_id);
