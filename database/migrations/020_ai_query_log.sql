-- Text2SQL 每轮查询的追加式留档。
-- ai_conversation_state.query_trace 只保留每个会话最近一次查询，本表保留完整历史轨迹，
-- 用于回溯“某个结论当时是用哪套槽位/模板/SQL 查出来的”。

CREATE TABLE IF NOT EXISTS ai_query_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    conversation_id BIGINT UNSIGNED NOT NULL COMMENT 'AI 会话 ID',
    thread_id VARCHAR(255) NULL COMMENT 'LangGraph thread_id',
    question TEXT NOT NULL COMMENT '当轮用户问题原文',
    question_hash CHAR(16) NOT NULL COMMENT '问题指纹，用于关联应用日志',
    dataset VARCHAR(64) NOT NULL COMMENT '数据集键',
    dataset_label VARCHAR(64) NULL COMMENT '数据集展示名',
    slots JSON NOT NULL COMMENT '该轮抽取的槽位快照',
    template TEXT NULL COMMENT '查询模板摘要',
    sql_text LONGTEXT NULL COMMENT '当轮生成并实际执行的查询语句',
    row_count INT NOT NULL DEFAULT 0 COMMENT '返回行数',
    truncated TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否被返回上限截断',
    unit VARCHAR(32) NULL COMMENT '结果单位',
    executed_at DATETIME(3) NULL COMMENT '查询执行时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '留档时间',
    PRIMARY KEY (id),
    KEY idx_ai_query_log_conversation (conversation_id, created_at),
    KEY idx_ai_query_log_thread (thread_id),
    KEY idx_ai_query_log_dataset_time (dataset, created_at),
    CONSTRAINT fk_ai_query_log_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 查询留档';
