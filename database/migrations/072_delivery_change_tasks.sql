-- 交期变化待办与采购订单的实际变更记录关联。
CREATE TABLE IF NOT EXISTS delivery_change_tasks (
    id INT NOT NULL AUTO_INCREMENT,
    po_id BIGINT UNSIGNED NOT NULL,
    assignee_id BIGINT UNSIGNED NULL,
    latest_update_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(20) NOT NULL,
    active_slot INT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    completed_at DATETIME(3) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_delivery_change_active (po_id, active_slot),
    KEY ix_delivery_change_assignee (assignee_id, status),
    CONSTRAINT fk_delivery_change_order FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_delivery_change_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id),
    CONSTRAINT fk_delivery_change_update FOREIGN KEY (latest_update_id) REFERENCES supplier_delivery_updates (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='交期变化待办';
