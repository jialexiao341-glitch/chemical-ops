ALTER TABLE async_task_executions
    ADD COLUMN started_at DATETIME(3) NULL,
    ADD COLUMN finished_at DATETIME(3) NULL,
    ADD INDEX ix_task_execution_finished_at (finished_at);
