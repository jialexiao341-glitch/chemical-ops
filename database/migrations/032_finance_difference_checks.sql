CREATE TABLE finance_difference_checks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id BIGINT UNSIGNED NOT NULL,
    scope_key VARCHAR(64) NOT NULL,
    target_label VARCHAR(255) NOT NULL,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    assignee_id BIGINT UNSIGNED NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    finding VARCHAR(2000) NULL,
    checked_by BIGINT UNSIGNED NULL,
    checked_at DATETIME(3) NULL,
    reviewed_by BIGINT UNSIGNED NULL,
    reviewed_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_finance_check_scope (order_id, scope_key),
    CONSTRAINT fk_finance_check_order FOREIGN KEY (order_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_finance_check_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_finance_check_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id),
    CONSTRAINT fk_finance_check_checker FOREIGN KEY (checked_by) REFERENCES sys_users (id),
    CONSTRAINT fk_finance_check_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单行及财务单据差异核查';

CREATE TABLE finance_difference_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    check_id BIGINT UNSIGNED NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(20) NOT NULL,
    assignee_id BIGINT UNSIGNED NULL,
    finding VARCHAR(2000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_finance_check_event_check (check_id, id),
    CONSTRAINT fk_finance_check_event_check FOREIGN KEY (check_id) REFERENCES finance_difference_checks (id),
    CONSTRAINT fk_finance_check_event_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id),
    CONSTRAINT fk_finance_check_event_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='财务差异核查追加式处理记录';
