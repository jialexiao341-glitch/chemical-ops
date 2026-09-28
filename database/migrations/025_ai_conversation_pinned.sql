ALTER TABLE ai_conversations
    ADD COLUMN pinned TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否置顶' AFTER status;
