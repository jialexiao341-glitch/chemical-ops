-- AI 模型管理：在数据库中保存可切换的 OpenAI 兼容模型配置。
-- api_key 允许为空，表示沿用环境变量 OPENAI_API_KEY；接口只返回掩码。
CREATE TABLE IF NOT EXISTS ai_model_profiles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    profile_name VARCHAR(64) NOT NULL COMMENT '模型配置显示名称，全局唯一',
    model VARCHAR(128) NOT NULL COMMENT '上游模型标识',
    base_url VARCHAR(255) NOT NULL COMMENT 'OpenAI 兼容接口地址',
    api_key VARCHAR(512) NULL COMMENT '接口密钥；为空时回退 OPENAI_API_KEY',
    context_window INT UNSIGNED NULL COMMENT '上下文窗口，仅用于展示与配置核对',
    max_tokens INT UNSIGNED NULL COMMENT '单次最大输出 token 数',
    temperature DECIMAL(3,2) NOT NULL DEFAULT 0.20,
    timeout_seconds SMALLINT UNSIGNED NOT NULL DEFAULT 60,
    max_retries TINYINT UNSIGNED NOT NULL DEFAULT 2,
    max_concurrency SMALLINT UNSIGNED NOT NULL DEFAULT 8,
    stream_usage TINYINT(1) NOT NULL DEFAULT 0,
    is_default TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否为当前使用模型',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_ai_model_profile_name (profile_name),
    KEY ix_ai_model_profile_default (is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='可切换的 AI 模型配置';

INSERT IGNORE INTO ai_model_profiles (
    profile_name, model, base_url, api_key, context_window, max_tokens,
    temperature, timeout_seconds, max_retries, max_concurrency, is_default
)
VALUES
    ('DeepSeek Flash', 'deepseek-flash', 'https://api.deepseek.com', NULL, 131072, 65536, 0.20, 60, 2, 8, 0),
    ('MaxApi', 'deepseek-v4.1-flash', 'https://ai.max66.xyz/v1', NULL, 1048576, 65536, 0.20, 120, 2, 8, 1);

INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES
    ('ai.models.read', '查看 AI 模型管理', 'API', 'ai.models', 'read'),
    ('ai.models.write', '管理 AI 模型配置', 'API', 'ai.models', 'write');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id
FROM sys_roles role
JOIN sys_permissions permission
WHERE role.role_code = 'SYS_ADMIN'
AND permission.permission_code IN ('ai.models.read', 'ai.models.write');