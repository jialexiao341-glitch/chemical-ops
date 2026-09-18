-- ChemicalOps 站内通知增量迁移，适用于已经存在的开发数据库。
-- 执行前请确认当前数据库连接的是 chemicalops。

CREATE TABLE IF NOT EXISTS sys_notifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    recipient_id BIGINT UNSIGNED NOT NULL,
    notification_type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    related_type VARCHAR(64) NULL,
    related_id BIGINT UNSIGNED NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    read_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_notification_recipient_read_time (recipient_id, is_read, created_at),
    KEY idx_notification_related (related_type, related_id),
    CONSTRAINT fk_notification_recipient FOREIGN KEY (recipient_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
