SET @task_poll_index_exists = (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = 'async_task_executions' AND index_name = 'ix_task_queue_poll');
SET @task_poll_index_sql = IF(@task_poll_index_exists = 0, 'CREATE INDEX ix_task_queue_poll ON async_task_executions (task_type, status, created_at, id)', 'SELECT 1');
PREPARE task_poll_index_statement FROM @task_poll_index_sql;
EXECUTE task_poll_index_statement;
DEALLOCATE PREPARE task_poll_index_statement;
