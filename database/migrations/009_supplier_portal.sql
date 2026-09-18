-- ChemicalOps 供应商门户账号与采购订单确认增量迁移。

CREATE TABLE IF NOT EXISTS supplier_portal_accounts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id BIGINT UNSIGNED NOT NULL COMMENT '系统用户 ID',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '绑定供应商 ID',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、INACTIVE',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_supplier_portal_user (user_id), UNIQUE KEY uk_supplier_portal_supplier_user (supplier_id, user_id), KEY idx_supplier_portal_supplier_status (supplier_id, status),
    CONSTRAINT fk_supplier_portal_user FOREIGN KEY (user_id) REFERENCES sys_users (id), CONSTRAINT fk_supplier_portal_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='供应商门户账号绑定';
