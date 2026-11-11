-- 模型思考强度：low / medium / high；为空表示不向服务端显式指定。
ALTER TABLE ai_model_profiles
    ADD COLUMN reasoning_effort VARCHAR(16) NULL COMMENT '思考强度：low/medium/high，空表示使用服务端默认' AFTER max_tokens;