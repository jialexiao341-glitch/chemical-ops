CREATE TABLE quality_review_corrections (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    review_id BIGINT UNSIGNED NOT NULL,
    item_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    note VARCHAR(2000) NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_quality_correction_review_item (review_id, item_name, id),
    CONSTRAINT fk_quality_correction_review FOREIGN KEY (review_id) REFERENCES quality_report_reviews (id),
    CONSTRAINT fk_quality_correction_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='报告检测项的修正处理历史';

INSERT IGNORE INTO sys_permissions (permission_code, permission_name, permission_type, resource, action)
VALUES ('quality.acceptances.review', '复核质量报告', 'API', 'quality.acceptances', 'review');

INSERT IGNORE INTO sys_roles (role_code, role_name, status)
VALUES ('QUALITY_MANAGER', '质量负责人', 'ACTIVE');

INSERT IGNORE INTO sys_role_permissions (role_id, permission_id)
SELECT role.id, permission.id FROM sys_roles role JOIN sys_permissions permission
WHERE role.role_code = 'QUALITY_MANAGER' AND permission.permission_code IN (
    'master.products.read', 'quality.acceptances.read', 'quality.acceptances.write',
    'quality.acceptances.review', 'system.files.read', 'system.files.download',
    'system.notifications.read'
);
