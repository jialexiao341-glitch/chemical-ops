CREATE TABLE IF NOT EXISTS async_task_executions (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    task_type VARCHAR(32) NOT NULL,
    business_id VARCHAR(64) NOT NULL,
    actor_id BIGINT NOT NULL,
    run_generation INT NOT NULL,
    business_revision INT NOT NULL DEFAULT 0,
    payload JSON NOT NULL,
    checkpoint JSON NOT NULL,
    status VARCHAR(24) NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    delivery_generation INT NOT NULL DEFAULT 0,
    fencing_token INT NOT NULL DEFAULT 0,
    lease_owner VARCHAR(64) NULL,
    lease_until DATETIME(3) NULL,
    heartbeat_at DATETIME(3) NULL,
    next_attempt_at DATETIME(3) NULL,
    error_code VARCHAR(64) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    UNIQUE KEY uq_task_business_generation (task_type, business_id, run_generation),
    KEY ix_task_status_lease (status, lease_until),
    KEY ix_task_actor (actor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS task_outbox (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    execution_id VARCHAR(32) NOT NULL,
    delivery_generation INT NOT NULL,
    routing_key VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    available_at DATETIME(3) NOT NULL,
    lease_owner VARCHAR(64) NULL,
    lease_until DATETIME(3) NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    created_at DATETIME(3) NOT NULL,
    UNIQUE KEY uq_task_outbox_delivery (execution_id, delivery_generation, routing_key),
    KEY ix_outbox_available (status, available_at),
    CONSTRAINT fk_outbox_execution FOREIGN KEY (execution_id) REFERENCES async_task_executions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS task_resource_locks (
    resource_key VARCHAR(96) NOT NULL PRIMARY KEY,
    execution_id VARCHAR(32) NOT NULL,
    CONSTRAINT fk_resource_execution FOREIGN KEY (execution_id) REFERENCES async_task_executions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
