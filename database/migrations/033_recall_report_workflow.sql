CREATE TABLE recall_report_workflows (
    snapshot_id BIGINT UNSIGNED NOT NULL,
    owner_id BIGINT UNSIGNED NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    conclusion VARCHAR(2000) NULL,
    submitted_by BIGINT UNSIGNED NULL,
    submitted_at DATETIME(3) NULL,
    review_reason VARCHAR(2000) NULL,
    reviewed_by BIGINT UNSIGNED NULL,
    reviewed_at DATETIME(3) NULL,
    completed_at DATETIME(3) NULL,
    PRIMARY KEY (snapshot_id),
    KEY idx_recall_workflow_owner (owner_id, status),
    CONSTRAINT fk_recall_workflow_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_recall_workflow_owner FOREIGN KEY (owner_id) REFERENCES sys_users (id),
    CONSTRAINT fk_recall_workflow_submitter FOREIGN KEY (submitted_by) REFERENCES sys_users (id),
    CONSTRAINT fk_recall_workflow_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='召回演练报告人工确认流程';

CREATE TABLE recall_report_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    snapshot_id BIGINT UNSIGNED NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    action VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    owner_id BIGINT UNSIGNED NULL,
    conclusion VARCHAR(2000) NULL,
    review_reason VARCHAR(2000) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_recall_event_report (snapshot_id, id),
    CONSTRAINT fk_recall_event_snapshot FOREIGN KEY (snapshot_id) REFERENCES insight_snapshots (id),
    CONSTRAINT fk_recall_event_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id),
    CONSTRAINT fk_recall_event_owner FOREIGN KEY (owner_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='召回演练报告追加式确认记录';
