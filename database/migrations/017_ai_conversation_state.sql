-- AI 多轮查询结构化状态。LangGraph checkpoint 后续可独立迁移，避免污染用户消息表。

CREATE TABLE IF NOT EXISTS ai_conversation_state (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    conversation_id BIGINT UNSIGNED NOT NULL COMMENT 'AI 会话 ID',
    thread_id VARCHAR(255) NOT NULL COMMENT '稳定的 LangGraph thread_id',
    query_plan JSON NULL COMMENT '最近一次已校验的 QueryPlan',
    query_trace JSON NULL COMMENT '最近一次查询 Trace 摘要',
    permission_snapshot JSON NULL COMMENT '最近一次权限摘要，仅用于解释，不作为授权依据',
    attachment_refs JSON NULL COMMENT '附件 ID、解析状态和引用对象键',
    state_version INT NOT NULL DEFAULT 1 COMMENT '状态版本',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_state_conversation (conversation_id),
    UNIQUE KEY uk_ai_state_thread (thread_id),
    KEY idx_ai_state_updated (updated_at),
    CONSTRAINT fk_ai_state_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 会话结构化状态';
