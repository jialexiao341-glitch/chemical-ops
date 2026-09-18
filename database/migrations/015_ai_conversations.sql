-- ChemicalOps AI 会话和消息持久化增量迁移。

CREATE TABLE IF NOT EXISTS ai_conversations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id BIGINT UNSIGNED NOT NULL COMMENT '发起用户 ID',
    title VARCHAR(255) NULL COMMENT '会话标题',
    business_scene VARCHAR(64) NOT NULL DEFAULT 'GENERAL' COMMENT '业务场景',
    permission_snapshot JSON NOT NULL COMMENT '会话创建时的权限快照',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、ARCHIVED、CLOSED',
    last_message_at DATETIME(3) NULL COMMENT '最近消息时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_ai_conversation_user_status (user_id, status, last_message_at),
    CONSTRAINT fk_ai_conversation_user FOREIGN KEY (user_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 会话';

CREATE TABLE IF NOT EXISTS ai_messages (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    conversation_id BIGINT UNSIGNED NOT NULL COMMENT '会话 ID',
    message_role VARCHAR(20) NOT NULL COMMENT 'USER、ASSISTANT、SYSTEM、TOOL',
    content LONGTEXT NOT NULL COMMENT '消息内容',
    citations JSON NULL COMMENT '引用来源',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '消息时间',
    PRIMARY KEY (id),
    KEY idx_ai_message_conversation_time (conversation_id, created_at),
    CONSTRAINT fk_ai_message_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 消息';
