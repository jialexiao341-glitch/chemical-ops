-- ChemicalOps 统一幂等请求记录。

CREATE TABLE IF NOT EXISTS sys_idempotency_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    idempotency_key VARCHAR(128) NOT NULL COMMENT '客户端幂等键',
    actor_key CHAR(64) NOT NULL COMMENT '当前用户令牌摘要，隔离不同用户',
    method VARCHAR(10) NOT NULL COMMENT 'HTTP 方法',
    path VARCHAR(500) NOT NULL COMMENT '请求路径',
    request_hash CHAR(64) NOT NULL COMMENT '请求体摘要',
    status VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS' COMMENT 'IN_PROGRESS、COMPLETED',
    response_status SMALLINT UNSIGNED NULL COMMENT '首次响应 HTTP 状态码',
    response_body JSON NULL COMMENT '首次响应 JSON 内容',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    expires_at DATETIME(3) NOT NULL COMMENT '幂等记录过期时间',
    PRIMARY KEY (id), UNIQUE KEY uk_idempotency_actor_key (actor_key, idempotency_key), KEY idx_idempotency_expiry (expires_at), KEY idx_idempotency_path_time (path, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='统一幂等请求记录';
