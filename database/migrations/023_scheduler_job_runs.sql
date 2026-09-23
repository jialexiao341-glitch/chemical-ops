CREATE TABLE IF NOT EXISTS scheduler_job_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id VARCHAR(32) NOT NULL,
    task_name VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL COMMENT 'RUNNING、SUCCEEDED、FAILED',
    attempt_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    finished_at DATETIME(3) NULL,
    result_json JSON NULL,
    error_type VARCHAR(128) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_scheduler_job_run_id (run_id),
    KEY idx_scheduler_job_run_task_started (task_name, started_at),
    KEY idx_scheduler_job_run_status_started (status, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='后台定时任务执行历史';
