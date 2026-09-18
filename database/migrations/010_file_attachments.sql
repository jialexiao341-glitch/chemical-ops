-- ChemicalOps 文件附件关联增量迁移。

CREATE TABLE IF NOT EXISTS sys_file_attachments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    file_id BIGINT UNSIGNED NOT NULL COMMENT '文件 ID',
    resource_type VARCHAR(64) NOT NULL COMMENT '业务资源类型',
    resource_id BIGINT UNSIGNED NOT NULL COMMENT '业务资源 ID',
    created_by BIGINT UNSIGNED NOT NULL COMMENT '关联创建人用户 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_file_attachment_resource (resource_type, resource_id, file_id),
    KEY idx_file_attachment_resource (resource_type, resource_id, created_at),
    KEY idx_file_attachment_file (file_id, created_at),
    CONSTRAINT fk_file_attachment_file FOREIGN KEY (file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_file_attachment_creator FOREIGN KEY (created_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='业务文件附件关联';
