CREATE TABLE exception_action_decisions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    exception_id BIGINT UNSIGNED NOT NULL,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    decision VARCHAR(20) NOT NULL,
    reason VARCHAR(2000) NOT NULL,
    task_id BIGINT UNSIGNED NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_exception_action_exception (exception_id),
    CONSTRAINT fk_exception_action_exception FOREIGN KEY (exception_id) REFERENCES operation_exceptions (id),
    CONSTRAINT fk_exception_action_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_exception_action_task FOREIGN KEY (task_id) REFERENCES operation_tasks (id),
    CONSTRAINT fk_exception_action_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='运营异常处置建议当前决策';

CREATE TABLE exception_action_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    decision_id BIGINT UNSIGNED NOT NULL,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    decision VARCHAR(20) NOT NULL,
    reason VARCHAR(2000) NOT NULL,
    task_id BIGINT UNSIGNED NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_exception_action_event_decision (decision_id, id),
    CONSTRAINT fk_exception_action_event_decision FOREIGN KEY (decision_id) REFERENCES exception_action_decisions (id),
    CONSTRAINT fk_exception_action_event_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_exception_action_event_task FOREIGN KEY (task_id) REFERENCES operation_tasks (id),
    CONSTRAINT fk_exception_action_event_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='运营异常处置建议追加式决策记录';
