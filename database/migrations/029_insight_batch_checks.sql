CREATE TABLE insight_snapshots (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    kind VARCHAR(40) NOT NULL,
    object_id BIGINT UNSIGNED NOT NULL,
    result_json JSON NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_insight_snapshot_object (kind, object_id, created_by, id),
    CONSTRAINT fk_insight_snapshot_creator FOREIGN KEY (created_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='业务分析结果及来源快照';

CREATE TABLE batch_check_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_id BIGINT UNSIGNED NOT NULL,
    balance_id BIGINT UNSIGNED NOT NULL,
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
    UNIQUE KEY uk_batch_check_balance (batch_id, balance_id),
    KEY idx_batch_check_assignee (assignee_id, status),
    CONSTRAINT fk_batch_check_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_batch_check_balance FOREIGN KEY (balance_id) REFERENCES inventory_balances (id),
    CONSTRAINT fk_batch_check_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_batch_check_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id),
    CONSTRAINT fk_batch_check_checker FOREIGN KEY (checked_by) REFERENCES sys_users (id),
    CONSTRAINT fk_batch_check_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='逐库位批次影响核查';

CREATE TABLE batch_check_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    check_id BIGINT UNSIGNED NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(20) NOT NULL,
    assignee_id BIGINT UNSIGNED NULL,
    finding VARCHAR(2000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_batch_check_event_check (check_id, id),
    CONSTRAINT fk_batch_check_event_check FOREIGN KEY (check_id) REFERENCES batch_check_items (id),
    CONSTRAINT fk_batch_check_event_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id),
    CONSTRAINT fk_batch_check_event_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='批次核查追加式处理记录';
