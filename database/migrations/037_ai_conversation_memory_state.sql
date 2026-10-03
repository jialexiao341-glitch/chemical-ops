ALTER TABLE ai_conversation_state
    ADD COLUMN memory_state JSON NULL COMMENT '会话级短期记忆：目标、焦点实体、槽位、待补充项和有限上下文' AFTER thread_id;
