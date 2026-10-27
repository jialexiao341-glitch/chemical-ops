CREATE TABLE IF NOT EXISTS ai_operation_suggestions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    exception_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    handled_by BIGINT UNSIGNED NULL,
    handled_at DATETIME(3) NULL,
    task_id BIGINT UNSIGNED NULL,
    created_at DATETIME(3) NOT NULL,
    CONSTRAINT uq_ai_operation_suggestion_exception UNIQUE (exception_id),
    CONSTRAINT fk_ai_suggestion_exception FOREIGN KEY (exception_id) REFERENCES operation_exceptions(id),
    CONSTRAINT fk_ai_suggestion_user FOREIGN KEY (handled_by) REFERENCES sys_users(id),
    CONSTRAINT fk_ai_suggestion_task FOREIGN KEY (task_id) REFERENCES operation_tasks(id),
    INDEX ix_ai_suggestion_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
