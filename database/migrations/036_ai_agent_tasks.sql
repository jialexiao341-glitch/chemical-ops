CREATE TABLE IF NOT EXISTS ai_agent_tasks (
    id VARCHAR(32) NOT NULL COMMENT '随机任务 ID',
    user_id BIGINT UNSIGNED NOT NULL COMMENT '任务所属用户',
    status VARCHAR(24) NOT NULL COMMENT 'RUNNING、WAITING_INPUT、SUCCEEDED、FAILED、CANCELLED',
    revision INT NOT NULL DEFAULT 0 COMMENT '乐观并发版本',
    payload JSON NOT NULL COMMENT '用户输入与公开工具轨迹，不保存思维链',
    reply TEXT NOT NULL COMMENT '任务回复或等待原因',
    error_code VARCHAR(64) NULL COMMENT '规范化错误类别',
    created_at DATETIME(3) NOT NULL COMMENT 'UTC 创建时间',
    updated_at DATETIME(3) NOT NULL COMMENT 'UTC 更新时间',
    PRIMARY KEY (id),
    KEY ix_ai_agent_tasks_user_id (user_id),
    CONSTRAINT fk_ai_agent_task_user FOREIGN KEY (user_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='只读采购 Agent 任务';
