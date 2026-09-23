-- 登录防护计数与用户令牌版本，用于限速和立即撤销既有访问令牌。

ALTER TABLE sys_users
    ADD COLUMN token_version INT UNSIGNED NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS sys_login_attempts (
    scope_key CHAR(64) NOT NULL COMMENT '登录限速范围的 SHA-256 指纹',
    failure_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    window_started_at DATETIME(3) NOT NULL,
    locked_until DATETIME(3) NULL,
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (scope_key),
    KEY idx_login_attempt_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录失败限速记录';
