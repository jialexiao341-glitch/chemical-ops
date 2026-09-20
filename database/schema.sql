-- ChemicalOps MVP database schema
-- MySQL 8.0+
-- All business writes should go through the service layer. The checks below
-- protect the most important invariants at database level as well.

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS sys_audit_logs;
DROP TABLE IF EXISTS ai_action_approvals;
DROP TABLE IF EXISTS ai_tool_calls;
DROP TABLE IF EXISTS ai_run_steps;
DROP TABLE IF EXISTS ai_runs;
DROP TABLE IF EXISTS ai_messages;
DROP TABLE IF EXISTS ai_conversations;
DROP TABLE IF EXISTS price_forecast_items;
DROP TABLE IF EXISTS price_forecast_runs;
DROP TABLE IF EXISTS market_price_records;
DROP TABLE IF EXISTS knowledge_document_chunks;
DROP TABLE IF EXISTS knowledge_documents;
DROP TABLE IF EXISTS operation_task_comments;
DROP TABLE IF EXISTS operation_tasks;
DROP TABLE IF EXISTS operation_exceptions;
DROP TABLE IF EXISTS sys_notifications;
DROP TABLE IF EXISTS finance_settlements;
DROP TABLE IF EXISTS finance_payments;
DROP TABLE IF EXISTS finance_invoices;
DROP TABLE IF EXISTS finance_reconciliations;
DROP TABLE IF EXISTS replenishment_items;
DROP TABLE IF EXISTS replenishment_requests;
DROP TABLE IF EXISTS inventory_return_items;
DROP TABLE IF EXISTS inventory_return_requests;
DROP TABLE IF EXISTS supplier_portal_accounts;
DROP TABLE IF EXISTS sys_file_attachments;
DROP TABLE IF EXISTS sys_idempotency_records;
DROP TABLE IF EXISTS quality_acceptances;
DROP TABLE IF EXISTS inventory_transactions;
DROP TABLE IF EXISTS inventory_fifo_outbound_allocations;
DROP TABLE IF EXISTS inventory_fifo_outbound_requests;
DROP TABLE IF EXISTS inventory_cost_allocations;
DROP TABLE IF EXISTS inventory_cost_layers;
DROP TABLE IF EXISTS inventory_balance_status_logs;
DROP TABLE IF EXISTS inventory_balances;
DROP TABLE IF EXISTS inventory_batches;
DROP TABLE IF EXISTS inventory_issue_items;
DROP TABLE IF EXISTS inventory_issue_requests;
DROP TABLE IF EXISTS inventory_transfer_items;
DROP TABLE IF EXISTS inventory_transfer_requests;
DROP TABLE IF EXISTS inventory_stocktake_items;
DROP TABLE IF EXISTS inventory_stocktake_requests;
DROP TABLE IF EXISTS warehouse_locations;
DROP TABLE IF EXISTS warehouses;
DROP TABLE IF EXISTS delivery_items;
DROP TABLE IF EXISTS deliveries;
DROP TABLE IF EXISTS purchase_order_events;
DROP TABLE IF EXISTS purchase_order_approvals;
DROP TABLE IF EXISTS purchase_order_items;
DROP TABLE IF EXISTS purchase_orders;
DROP TABLE IF EXISTS quote_comparison_items;
DROP TABLE IF EXISTS quote_comparisons;
DROP TABLE IF EXISTS supplier_quote_items;
DROP TABLE IF EXISTS supplier_quotes;
DROP TABLE IF EXISTS rfq_suppliers;
DROP TABLE IF EXISTS rfq_items;
DROP TABLE IF EXISTS rfqs;
DROP TABLE IF EXISTS purchase_request_approvals;
DROP TABLE IF EXISTS purchase_request_items;
DROP TABLE IF EXISTS purchase_requests;
DROP TABLE IF EXISTS supplier_evaluations;
DROP TABLE IF EXISTS supplier_products;
DROP TABLE IF EXISTS supplier_qualifications;
DROP TABLE IF EXISTS supplier_contacts;
DROP TABLE IF EXISTS suppliers;
DROP TABLE IF EXISTS md_product_substitutes;
DROP TABLE IF EXISTS md_product_parameters;
DROP TABLE IF EXISTS md_products;
DROP TABLE IF EXISTS md_chemicals;
DROP TABLE IF EXISTS md_product_categories;
DROP TABLE IF EXISTS md_units;
DROP TABLE IF EXISTS sys_files;
DROP TABLE IF EXISTS sys_role_permissions;
DROP TABLE IF EXISTS sys_user_roles;
DROP TABLE IF EXISTS sys_permissions;
DROP TABLE IF EXISTS sys_roles;
DROP TABLE IF EXISTS sys_users;
DROP TABLE IF EXISTS sys_departments;

CREATE TABLE sys_departments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    parent_id BIGINT UNSIGNED NULL COMMENT '上级部门 ID，根部门为空',
    department_code VARCHAR(64) NOT NULL COMMENT '部门编码',
    department_name VARCHAR(128) NOT NULL COMMENT '部门名称',
    manager_id BIGINT UNSIGNED NULL COMMENT '部门负责人用户 ID',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE 启用，INACTIVE 停用',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_department_code (department_code),
    KEY idx_department_parent_status (parent_id, status),
    CONSTRAINT fk_department_parent FOREIGN KEY (parent_id) REFERENCES sys_departments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='组织部门';

CREATE TABLE sys_users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    username VARCHAR(64) NOT NULL COMMENT '登录用户名',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希，不保存明文密码',
    display_name VARCHAR(100) NOT NULL COMMENT '显示姓名',
    department_id BIGINT UNSIGNED NULL COMMENT '所属部门 ID，系统级账号可为空',
    email VARCHAR(255) NULL COMMENT '邮箱',
    phone VARCHAR(32) NULL COMMENT '手机号',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE 启用，LOCKED 锁定，INACTIVE 停用',
    last_login_at DATETIME(3) NULL COMMENT '最近登录时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_username (username),
    UNIQUE KEY uk_user_email (email),
    KEY idx_user_department_status (department_id, status),
    KEY idx_user_status_name (status, display_name),
    CONSTRAINT fk_user_department FOREIGN KEY (department_id) REFERENCES sys_departments (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统用户';

CREATE TABLE sys_roles (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    role_code VARCHAR(64) NOT NULL COMMENT '角色编码',
    role_name VARCHAR(100) NOT NULL COMMENT '角色名称',
    description VARCHAR(500) NULL COMMENT '角色说明',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT '角色状态',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_code (role_code),
    KEY idx_role_status_name (status, role_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统角色';

CREATE TABLE sys_permissions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    permission_code VARCHAR(128) NOT NULL COMMENT '权限编码，例如 procurement.request.approve',
    permission_name VARCHAR(128) NOT NULL COMMENT '权限名称',
    permission_type VARCHAR(20) NOT NULL COMMENT 'MENU 菜单，API 接口，DATA 数据范围',
    resource VARCHAR(128) NOT NULL COMMENT '资源标识',
    action VARCHAR(64) NOT NULL COMMENT '操作标识',
    description VARCHAR(500) NULL COMMENT '权限说明',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_code (permission_code),
    UNIQUE KEY uk_permission_resource_action (resource, action),
    KEY idx_permission_type_resource (permission_type, resource)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统权限';

CREATE TABLE sys_user_roles (
    user_id BIGINT UNSIGNED NOT NULL COMMENT '用户 ID',
    role_id BIGINT UNSIGNED NOT NULL COMMENT '角色 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '分配时间',
    PRIMARY KEY (user_id, role_id),
    KEY idx_user_role_role (role_id, user_id),
    CONSTRAINT fk_user_role_user FOREIGN KEY (user_id) REFERENCES sys_users (id),
    CONSTRAINT fk_user_role_role FOREIGN KEY (role_id) REFERENCES sys_roles (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户角色关联';

CREATE TABLE sys_role_permissions (
    role_id BIGINT UNSIGNED NOT NULL COMMENT '角色 ID',
    permission_id BIGINT UNSIGNED NOT NULL COMMENT '权限 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '分配时间',
    PRIMARY KEY (role_id, permission_id),
    KEY idx_role_permission_permission (permission_id, role_id),
    CONSTRAINT fk_role_permission_role FOREIGN KEY (role_id) REFERENCES sys_roles (id),
    CONSTRAINT fk_role_permission_permission FOREIGN KEY (permission_id) REFERENCES sys_permissions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色权限关联';

CREATE TABLE sys_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    file_name VARCHAR(255) NOT NULL COMMENT '原始文件名',
    object_key VARCHAR(500) NOT NULL COMMENT 'MinIO 对象键，不保存文件二进制',
    mime_type VARCHAR(128) NOT NULL COMMENT 'MIME 类型',
    file_size_bytes BIGINT UNSIGNED NOT NULL COMMENT '文件字节数',
    sha256_hash CHAR(64) NOT NULL COMMENT '文件 SHA-256 哈希',
    file_category VARCHAR(32) NOT NULL COMMENT 'TDS、SDS、COA、QUOTE、QUALIFICATION、REPORT 等',
    access_level VARCHAR(20) NOT NULL DEFAULT 'INTERNAL' COMMENT 'PRIVATE、INTERNAL、PUBLIC',
    uploader_id BIGINT UNSIGNED NOT NULL COMMENT '上传用户 ID',
    parse_status VARCHAR(20) NOT NULL DEFAULT 'NOT_STARTED' COMMENT 'NOT_STARTED、PROCESSING、SUCCEEDED、FAILED、CONFIRMED',
    parse_error VARCHAR(1000) NULL COMMENT '解析失败信息',
    uploaded_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '上传时间',
    expires_at DATETIME(3) NULL COMMENT '文件访问或业务有效期',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_file_object_key (object_key),
    KEY idx_file_hash (sha256_hash),
    KEY idx_file_category_parse (file_category, parse_status),
    KEY idx_file_expiry (expires_at),
    CONSTRAINT fk_file_uploader FOREIGN KEY (uploader_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文件元数据';

CREATE TABLE sys_file_attachments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', file_id BIGINT UNSIGNED NOT NULL COMMENT '文件 ID', resource_type VARCHAR(64) NOT NULL COMMENT '业务资源类型', resource_id BIGINT UNSIGNED NOT NULL COMMENT '业务资源 ID', created_by BIGINT UNSIGNED NOT NULL COMMENT '关联创建人用户 ID', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id), UNIQUE KEY uk_file_attachment_resource (resource_type, resource_id, file_id), KEY idx_file_attachment_resource (resource_type, resource_id, created_at), KEY idx_file_attachment_file (file_id, created_at),
    CONSTRAINT fk_file_attachment_file FOREIGN KEY (file_id) REFERENCES sys_files (id), CONSTRAINT fk_file_attachment_creator FOREIGN KEY (created_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='业务文件附件关联';

CREATE TABLE sys_idempotency_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', idempotency_key VARCHAR(128) NOT NULL COMMENT '客户端幂等键', actor_key CHAR(64) NOT NULL COMMENT '用户令牌摘要', method VARCHAR(10) NOT NULL COMMENT 'HTTP 方法', path VARCHAR(500) NOT NULL COMMENT '请求路径', request_hash CHAR(64) NOT NULL COMMENT '请求体摘要', status VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS' COMMENT 'IN_PROGRESS、COMPLETED', response_status SMALLINT UNSIGNED NULL COMMENT '首次响应状态码', response_body JSON NULL COMMENT '首次响应 JSON 内容', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间', expires_at DATETIME(3) NOT NULL COMMENT '过期时间',
    PRIMARY KEY (id), UNIQUE KEY uk_idempotency_actor_key (actor_key, idempotency_key), KEY idx_idempotency_expiry (expires_at), KEY idx_idempotency_path_time (path, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='统一幂等请求记录';

CREATE TABLE sys_notifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    recipient_id BIGINT UNSIGNED NOT NULL COMMENT '接收用户 ID',
    notification_type VARCHAR(32) NOT NULL COMMENT '通知类型',
    title VARCHAR(255) NOT NULL COMMENT '通知标题',
    content TEXT NOT NULL COMMENT '通知内容',
    related_type VARCHAR(64) NULL COMMENT '关联业务类型',
    related_id BIGINT UNSIGNED NULL COMMENT '关联业务 ID',
    is_read TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已读，0 未读，1 已读',
    read_at DATETIME(3) NULL COMMENT '阅读时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    KEY idx_notification_recipient_read_time (recipient_id, is_read, created_at),
    KEY idx_notification_related (related_type, related_id),
    CONSTRAINT fk_notification_recipient FOREIGN KEY (recipient_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='站内通知';

CREATE TABLE md_units (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    unit_code VARCHAR(32) NOT NULL COMMENT '单位编码，例如 KG、L、PCS',
    unit_name VARCHAR(64) NOT NULL COMMENT '单位名称',
    dimension VARCHAR(32) NOT NULL COMMENT 'QUANTITY、MASS、VOLUME 等量纲',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT '单位状态',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_unit_code (unit_code),
    KEY idx_unit_dimension_status (dimension, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='计量单位字典';

CREATE TABLE md_product_categories (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    parent_id BIGINT UNSIGNED NULL COMMENT '父分类 ID',
    category_code VARCHAR(64) NOT NULL COMMENT '分类编码',
    category_name VARCHAR(128) NOT NULL COMMENT '分类名称',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT '分类状态',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_category_code (category_code),
    KEY idx_category_parent_status (parent_id, status),
    CONSTRAINT fk_category_parent FOREIGN KEY (parent_id) REFERENCES md_product_categories (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品分类树';

CREATE TABLE md_chemicals (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    chemical_name VARCHAR(255) NOT NULL COMMENT '化学品中文名称',
    english_name VARCHAR(255) NULL COMMENT '化学品英文名称',
    alias_text TEXT NULL COMMENT '别名，建议由服务层拆分或维护搜索索引',
    cas_no VARCHAR(32) NULL COMMENT 'CAS 号，无 CAS 或尚未确认时为空',
    chemical_formula VARCHAR(128) NULL COMMENT '化学式',
    molecular_weight DECIMAL(18,6) NULL COMMENT '分子量',
    hazard_class VARCHAR(128) NULL COMMENT '危险性分类摘要',
    source_text VARCHAR(500) NULL COMMENT '基础资料来源说明',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE 启用，INACTIVE 停用',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_chemical_cas (cas_no),
    KEY idx_chemical_name_status (chemical_name, status),
    KEY idx_chemical_english_name (english_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='化学品基础信息';

CREATE TABLE md_products (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    product_code VARCHAR(64) NOT NULL COMMENT '企业内部产品编码',
    product_name VARCHAR(255) NOT NULL COMMENT '采购产品名称',
    chemical_id BIGINT UNSIGNED NOT NULL COMMENT '所属化学品 ID',
    category_id BIGINT UNSIGNED NULL COMMENT '产品分类 ID',
    model VARCHAR(128) NULL COMMENT '产品型号或牌号',
    purity_value DECIMAL(18,6) NULL COMMENT '纯度数值',
    purity_unit VARCHAR(20) NULL DEFAULT '%' COMMENT '纯度单位，通常为 %',
    packaging_spec VARCHAR(255) NULL COMMENT '包装规格，例如 25 KG/袋',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '交易计量单位 ID',
    parameter_json JSON NULL COMMENT '不固定的扩展参数；可检索参数应落 md_product_parameters',
    version_no INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '产品资料版本号',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、INACTIVE、PENDING_CONFIRMATION',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_code (product_code),
    KEY idx_product_chemical_status (chemical_id, status),
    KEY idx_product_category_status (category_id, status),
    KEY idx_product_name_status (product_name, status),
    CONSTRAINT fk_product_chemical FOREIGN KEY (chemical_id) REFERENCES md_chemicals (id),
    CONSTRAINT fk_product_category FOREIGN KEY (category_id) REFERENCES md_product_categories (id),
    CONSTRAINT fk_product_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_product_purity CHECK (purity_value IS NULL OR (purity_value >= 0 AND purity_value <= 100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='可采购产品规格';

CREATE TABLE md_product_parameters (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    parameter_code VARCHAR(64) NOT NULL COMMENT '参数编码',
    parameter_name VARCHAR(128) NOT NULL COMMENT '参数名称',
    value_text VARCHAR(500) NULL COMMENT '原始文本值',
    numeric_value DECIMAL(18,6) NULL COMMENT '单值数值',
    unit_id BIGINT UNSIGNED NULL COMMENT '参数单位 ID',
    min_value DECIMAL(18,6) NULL COMMENT '允许或规格下限',
    max_value DECIMAL(18,6) NULL COMMENT '允许或规格上限',
    test_method VARCHAR(255) NULL COMMENT '检测方法',
    source_file_id BIGINT UNSIGNED NULL COMMENT '来源文件 ID',
    source_page INT UNSIGNED NULL COMMENT '来源页码',
    confirmation_status VARCHAR(20) NOT NULL DEFAULT 'UNCONFIRMED' COMMENT 'UNCONFIRMED、CONFIRMED、REJECTED',
    confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_parameter (product_id, parameter_code),
    KEY idx_parameter_search (parameter_name, numeric_value),
    KEY idx_parameter_source (source_file_id, source_page),
    KEY idx_parameter_confirmation (confirmation_status),
    CONSTRAINT fk_parameter_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_parameter_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT fk_parameter_file FOREIGN KEY (source_file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_parameter_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_parameter_range CHECK (min_value IS NULL OR max_value IS NULL OR min_value <= max_value)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品结构化技术参数';

CREATE TABLE md_product_substitutes (
    primary_product_id BIGINT UNSIGNED NOT NULL COMMENT '被替代的主产品 ID',
    substitute_product_id BIGINT UNSIGNED NOT NULL COMMENT '替代产品 ID',
    condition_text TEXT NULL COMMENT '适用条件',
    restriction_text TEXT NULL COMMENT '限制条件和风险',
    confirmation_status VARCHAR(20) NOT NULL DEFAULT 'UNCONFIRMED' COMMENT '替代关系确认状态',
    confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间',
    note VARCHAR(1000) NULL COMMENT '备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (primary_product_id, substitute_product_id),
    KEY idx_substitute_reverse (substitute_product_id, confirmation_status),
    CONSTRAINT fk_substitute_primary FOREIGN KEY (primary_product_id) REFERENCES md_products (id),
    CONSTRAINT fk_substitute_product FOREIGN KEY (substitute_product_id) REFERENCES md_products (id),
    CONSTRAINT fk_substitute_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_substitute_distinct CHECK (primary_product_id <> substitute_product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品替代关系';

CREATE TABLE suppliers (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    supplier_code VARCHAR(64) NOT NULL COMMENT '供应商编码',
    supplier_name VARCHAR(255) NOT NULL COMMENT '供应商名称',
    unified_credit_code VARCHAR(64) NULL COMMENT '统一社会信用代码或当地注册号',
    country_code CHAR(2) NOT NULL DEFAULT 'CN' COMMENT '国家/地区代码',
    region VARCHAR(128) NULL COMMENT '省/州/城市等地区',
    address VARCHAR(500) NULL COMMENT '详细地址',
    business_scope TEXT NULL COMMENT '业务范围',
    cooperation_level VARCHAR(20) NULL COMMENT '合作等级，例如 A/B/C',
    payment_terms VARCHAR(255) NULL COMMENT '默认付款条件',
    default_lead_days INT UNSIGNED NULL COMMENT '默认交期天数',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、SUSPENDED、INACTIVE',
    note VARCHAR(1000) NULL COMMENT '备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_supplier_code (supplier_code),
    UNIQUE KEY uk_supplier_credit_code (unified_credit_code),
    KEY idx_supplier_name_status (supplier_name, status),
    KEY idx_supplier_region_status (region, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商档案';

CREATE TABLE supplier_contacts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    contact_name VARCHAR(100) NOT NULL COMMENT '联系人姓名',
    job_title VARCHAR(100) NULL COMMENT '职位',
    phone VARCHAR(32) NULL COMMENT '电话',
    email VARCHAR(255) NULL COMMENT '邮箱',
    is_primary TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否主要联系人',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT '联系人状态',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_contact_supplier_primary (supplier_id, is_primary, status),
    KEY idx_contact_supplier_email (supplier_id, email),
    CONSTRAINT fk_contact_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商联系人';

CREATE TABLE supplier_qualifications (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    qualification_type VARCHAR(64) NOT NULL COMMENT '资质类型',
    qualification_no VARCHAR(128) NULL COMMENT '证书或资质编号',
    issued_at DATE NULL COMMENT '签发日期',
    expires_at DATE NULL COMMENT '到期日期',
    file_id BIGINT UNSIGNED NULL COMMENT '资质文件 ID',
    review_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、PASSED、REJECTED、EXPIRED',
    reviewed_by BIGINT UNSIGNED NULL COMMENT '审核人用户 ID',
    reviewed_at DATETIME(3) NULL COMMENT '审核时间',
    review_note VARCHAR(1000) NULL COMMENT '审核备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_supplier_qualification (supplier_id, qualification_type, qualification_no),
    KEY idx_qualification_expiry (expires_at, review_status),
    KEY idx_qualification_supplier_status (supplier_id, review_status),
    CONSTRAINT fk_qualification_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_qualification_file FOREIGN KEY (file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_qualification_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_qualification_dates CHECK (issued_at IS NULL OR expires_at IS NULL OR issued_at <= expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商资质';

CREATE TABLE supplier_products (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    supplier_model VARCHAR(128) NULL COMMENT '供应商侧型号/牌号',
    supplied_purity DECIMAL(18,6) NULL COMMENT '供应商可供纯度',
    moq_quantity DECIMAL(18,6) NULL COMMENT '最小起订量',
    moq_unit_id BIGINT UNSIGNED NULL COMMENT '最小起订量单位',
    standard_lead_days INT UNSIGNED NULL COMMENT '常规交期天数',
    capacity_note VARCHAR(500) NULL COMMENT '产能或供货能力说明',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、SUSPENDED、INACTIVE',
    note VARCHAR(1000) NULL COMMENT '备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_supplier_product (supplier_id, product_id),
    KEY idx_supplier_product_product_status (product_id, status),
    KEY idx_supplier_product_supplier_status (supplier_id, status),
    CONSTRAINT fk_supplier_product_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_supplier_product_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_supplier_product_moq_unit FOREIGN KEY (moq_unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_supplier_product_moq CHECK (moq_quantity IS NULL OR moq_quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商可供产品';

CREATE TABLE supplier_evaluations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    period_start DATE NOT NULL COMMENT '评价周期开始',
    period_end DATE NOT NULL COMMENT '评价周期结束',
    price_score DECIMAL(5,2) NULL COMMENT '价格得分',
    delivery_score DECIMAL(5,2) NULL COMMENT '交付得分',
    quality_score DECIMAL(5,2) NULL COMMENT '质量得分',
    service_score DECIMAL(5,2) NULL COMMENT '服务得分',
    total_score DECIMAL(5,2) NULL COMMENT '综合得分，由服务层按权重计算',
    evaluated_by BIGINT UNSIGNED NOT NULL COMMENT '评价人用户 ID',
    evaluated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '评价时间',
    evaluation_note VARCHAR(2000) NULL COMMENT '评价说明',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_supplier_evaluation_period (supplier_id, period_start, period_end),
    KEY idx_supplier_evaluation_period (supplier_id, period_end),
    CONSTRAINT fk_evaluation_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_evaluation_user FOREIGN KEY (evaluated_by) REFERENCES sys_users (id),
    CONSTRAINT chk_evaluation_dates CHECK (period_start <= period_end),
    CONSTRAINT chk_evaluation_scores CHECK (
        (price_score IS NULL OR price_score BETWEEN 0 AND 100) AND
        (delivery_score IS NULL OR delivery_score BETWEEN 0 AND 100) AND
        (quality_score IS NULL OR quality_score BETWEEN 0 AND 100) AND
        (service_score IS NULL OR service_score BETWEEN 0 AND 100) AND
        (total_score IS NULL OR total_score BETWEEN 0 AND 100)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商周期评价';

CREATE TABLE purchase_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    request_no VARCHAR(32) NOT NULL COMMENT '采购申请业务编号',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID',
    department_id BIGINT UNSIGNED NULL COMMENT '申请部门 ID，历史数据保留时可为空',
    purpose VARCHAR(1000) NOT NULL COMMENT '采购用途',
    priority VARCHAR(20) NOT NULL DEFAULT 'NORMAL' COMMENT 'LOW、NORMAL、HIGH、URGENT',
    budget_amount DECIMAL(18,6) NULL COMMENT '预算金额，未编制预算时为空',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '预算币种',
    expected_date DATE NULL COMMENT '期望到货日期',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVING、APPROVED、REJECTED、CANCELLED、PARTIAL、FULFILLED',
    submitted_at DATETIME(3) NULL COMMENT '提交审批时间',
    approved_at DATETIME(3) NULL COMMENT '审批通过时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    cancel_reason VARCHAR(1000) NULL COMMENT '取消原因',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_purchase_request_no (request_no),
    KEY idx_purchase_request_department_status (department_id, status),
    KEY idx_purchase_request_applicant_status (applicant_id, status),
    KEY idx_purchase_request_expected_status (expected_date, status),
    CONSTRAINT fk_purchase_request_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_purchase_request_department FOREIGN KEY (department_id) REFERENCES sys_departments (id),
    CONSTRAINT chk_purchase_request_budget CHECK (budget_amount IS NULL OR budget_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购申请主单';

CREATE TABLE purchase_request_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    request_id BIGINT UNSIGNED NOT NULL COMMENT '采购申请 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号',
    product_id BIGINT UNSIGNED NULL COMMENT '已确认产品 ID，待技术确认时为空',
    requested_name VARCHAR(255) NOT NULL COMMENT '申请时填写的产品名称快照',
    technical_requirements TEXT NULL COMMENT '技术要求',
    quantity DECIMAL(18,6) NOT NULL COMMENT '申请数量',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '申请单位 ID',
    budget_price DECIMAL(18,6) NULL COMMENT '预算单价',
    expected_date DATE NULL COMMENT '本明细期望到货日期',
    fulfilled_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '已满足数量',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、PARTIAL、FULFILLED、CANCELLED',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_purchase_request_item_line (request_id, line_no),
    KEY idx_request_item_product_status (product_id, status),
    KEY idx_request_item_request_status (request_id, status),
    CONSTRAINT fk_request_item_request FOREIGN KEY (request_id) REFERENCES purchase_requests (id),
    CONSTRAINT fk_request_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_request_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_request_item_quantity CHECK (quantity > 0 AND fulfilled_quantity >= 0 AND fulfilled_quantity <= quantity),
    CONSTRAINT chk_request_item_budget_price CHECK (budget_price IS NULL OR budget_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购申请明细';

CREATE TABLE purchase_request_approvals (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    request_id BIGINT UNSIGNED NOT NULL COMMENT '采购申请 ID',
    sequence_no SMALLINT UNSIGNED NOT NULL COMMENT '审批顺序',
    node_code VARCHAR(64) NOT NULL COMMENT '审批节点编码',
    node_name VARCHAR(128) NOT NULL COMMENT '审批节点名称',
    approver_id BIGINT UNSIGNED NULL COMMENT '实际审批人，待分配时为空',
    action VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、APPROVED、REJECTED、RETURNED、SKIPPED',
    opinion VARCHAR(2000) NULL COMMENT '审批意见',
    acted_at DATETIME(3) NULL COMMENT '审批动作时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_request_approval_sequence (request_id, sequence_no),
    KEY idx_request_approval_pending (approver_id, action),
    CONSTRAINT fk_request_approval_request FOREIGN KEY (request_id) REFERENCES purchase_requests (id),
    CONSTRAINT fk_request_approval_user FOREIGN KEY (approver_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购申请审批记录';

CREATE TABLE rfqs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    rfq_no VARCHAR(32) NOT NULL COMMENT '询价单业务编号',
    source_request_id BIGINT UNSIGNED NULL COMMENT '来源采购申请，手工询价时为空',
    requester_id BIGINT UNSIGNED NOT NULL COMMENT '询价人用户 ID',
    quote_deadline DATETIME(3) NULL COMMENT '报价截止时间',
    requested_delivery_date DATE NULL COMMENT '要求交付日期',
    delivery_requirements VARCHAR(1000) NULL COMMENT '交付要求',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SENT、RESPONDING、CLOSED、CANCELLED',
    sent_at DATETIME(3) NULL COMMENT '发出询价时间',
    closed_at DATETIME(3) NULL COMMENT '关闭询价时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_rfq_no (rfq_no),
    KEY idx_rfq_source_status (source_request_id, status),
    KEY idx_rfq_requester_status (requester_id, status),
    KEY idx_rfq_deadline_status (quote_deadline, status),
    CONSTRAINT fk_rfq_source_request FOREIGN KEY (source_request_id) REFERENCES purchase_requests (id),
    CONSTRAINT fk_rfq_requester FOREIGN KEY (requester_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='询价单主单';

CREATE TABLE rfq_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    rfq_id BIGINT UNSIGNED NOT NULL COMMENT '询价单 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号',
    source_request_item_id BIGINT UNSIGNED NULL COMMENT '来源采购申请明细 ID',
    product_id BIGINT UNSIGNED NULL COMMENT '询价产品 ID，待确认时为空',
    requested_name VARCHAR(255) NOT NULL COMMENT '询价产品名称快照',
    specification VARCHAR(1000) NULL COMMENT '规格描述',
    quantity DECIMAL(18,6) NOT NULL COMMENT '询价数量',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '询价单位 ID',
    required_delivery_date DATE NULL COMMENT '本行要求交期',
    technical_requirements TEXT NULL COMMENT '技术要求',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_rfq_item_line (rfq_id, line_no),
    KEY idx_rfq_item_product (product_id),
    KEY idx_rfq_item_source (source_request_item_id),
    CONSTRAINT fk_rfq_item_rfq FOREIGN KEY (rfq_id) REFERENCES rfqs (id),
    CONSTRAINT fk_rfq_item_request_item FOREIGN KEY (source_request_item_id) REFERENCES purchase_request_items (id),
    CONSTRAINT fk_rfq_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_rfq_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_rfq_item_quantity CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='询价单明细';

CREATE TABLE rfq_suppliers (
    rfq_id BIGINT UNSIGNED NOT NULL COMMENT '询价单 ID',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '受邀供应商 ID',
    invited_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '邀请时间',
    response_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、RESPONDED、DECLINED、EXPIRED',
    response_at DATETIME(3) NULL COMMENT '响应时间',
    invitation_channel VARCHAR(32) NULL COMMENT 'MANUAL、EMAIL、PORTAL 等',
    note VARCHAR(1000) NULL COMMENT '备注',
    PRIMARY KEY (rfq_id, supplier_id),
    KEY idx_rfq_supplier_status (supplier_id, response_status),
    CONSTRAINT fk_rfq_supplier_rfq FOREIGN KEY (rfq_id) REFERENCES rfqs (id),
    CONSTRAINT fk_rfq_supplier_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='询价供应商关联';

CREATE TABLE supplier_quotes (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    quote_no VARCHAR(32) NOT NULL COMMENT '报价单业务编号',
    rfq_id BIGINT UNSIGNED NOT NULL COMMENT '询价单 ID',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '报价供应商 ID',
    quote_version INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '同一供应商对同一询价的报价版本',
    quote_date DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '报价时间',
    valid_until DATE NULL COMMENT '报价有效期',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '报价币种',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、SELECTED、REJECTED、WITHDRAWN、EXPIRED',
    source_file_id BIGINT UNSIGNED NULL COMMENT '报价来源文件 ID',
    received_by BIGINT UNSIGNED NULL COMMENT '录入或接收人用户 ID',
    note VARCHAR(1000) NULL COMMENT '报价说明',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_quote_no (quote_no),
    UNIQUE KEY uk_quote_version (rfq_id, supplier_id, quote_version),
    KEY idx_quote_rfq_status (rfq_id, status),
    KEY idx_quote_supplier_date (supplier_id, quote_date),
    CONSTRAINT fk_quote_rfq FOREIGN KEY (rfq_id) REFERENCES rfqs (id),
    CONSTRAINT fk_quote_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_quote_file FOREIGN KEY (source_file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_quote_receiver FOREIGN KEY (received_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商报价主单';

CREATE TABLE supplier_quote_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    quote_id BIGINT UNSIGNED NOT NULL COMMENT '报价主单 ID',
    rfq_item_id BIGINT UNSIGNED NOT NULL COMMENT '询价明细 ID',
    supplier_product_id BIGINT UNSIGNED NULL COMMENT '供应商产品关联记录 ID',
    supplier_model VARCHAR(128) NULL COMMENT '供应商型号快照',
    quoted_quantity DECIMAL(18,6) NOT NULL COMMENT '报价数量',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '报价单位 ID',
    unit_price DECIMAL(18,6) NOT NULL COMMENT '含税或未税单价，含义由 tax_rate 配合解释',
    tax_rate DECIMAL(5,2) NULL COMMENT '税率百分比，未知时为空',
    moq_quantity DECIMAL(18,6) NULL COMMENT '该报价对应的最小起订量',
    moq_unit_id BIGINT UNSIGNED NULL COMMENT 'MOQ 单位',
    lead_days INT UNSIGNED NULL COMMENT '交期天数',
    payment_terms VARCHAR(255) NULL COMMENT '付款条件',
    note VARCHAR(1000) NULL COMMENT '报价明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_quote_item_rfq_item (quote_id, rfq_item_id),
    KEY idx_quote_item_rfq_item (rfq_item_id, unit_price),
    CONSTRAINT fk_quote_item_quote FOREIGN KEY (quote_id) REFERENCES supplier_quotes (id),
    CONSTRAINT fk_quote_item_rfq_item FOREIGN KEY (rfq_item_id) REFERENCES rfq_items (id),
    CONSTRAINT fk_quote_item_supplier_product FOREIGN KEY (supplier_product_id) REFERENCES supplier_products (id),
    CONSTRAINT fk_quote_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT fk_quote_item_moq_unit FOREIGN KEY (moq_unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_quote_item_values CHECK (quoted_quantity > 0 AND unit_price >= 0 AND (moq_quantity IS NULL OR moq_quantity > 0)),
    CONSTRAINT chk_quote_item_tax CHECK (tax_rate IS NULL OR tax_rate BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商报价明细';

CREATE TABLE quote_comparisons (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    comparison_no VARCHAR(32) NOT NULL COMMENT '报价比较编号',
    rfq_id BIGINT UNSIGNED NOT NULL COMMENT '被比较的询价单 ID',
    created_by BIGINT UNSIGNED NOT NULL COMMENT '创建人用户 ID',
    selected_quote_id BIGINT UNSIGNED NULL COMMENT '最终选定报价主单 ID',
    conclusion TEXT NULL COMMENT '比较结论',
    selection_reason TEXT NULL COMMENT '选择理由',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、CONFIRMED、CANCELLED',
    confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_comparison_no (comparison_no),
    KEY idx_comparison_rfq_status (rfq_id, status),
    KEY idx_comparison_creator (created_by, created_at),
    CONSTRAINT fk_comparison_rfq FOREIGN KEY (rfq_id) REFERENCES rfqs (id),
    CONSTRAINT fk_comparison_creator FOREIGN KEY (created_by) REFERENCES sys_users (id),
    CONSTRAINT fk_comparison_selected_quote FOREIGN KEY (selected_quote_id) REFERENCES supplier_quotes (id),
    CONSTRAINT fk_comparison_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='报价比较主单';

CREATE TABLE quote_comparison_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    comparison_id BIGINT UNSIGNED NOT NULL COMMENT '报价比较 ID',
    quote_id BIGINT UNSIGNED NOT NULL COMMENT '供应商报价 ID',
    rfq_item_id BIGINT UNSIGNED NOT NULL COMMENT '询价明细 ID',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID 快照关联',
    quoted_unit_price DECIMAL(18,6) NOT NULL COMMENT '比较时单价快照',
    total_amount DECIMAL(18,6) NULL COMMENT '比较时总金额快照',
    moq_quantity DECIMAL(18,6) NULL COMMENT 'MOQ 快照',
    lead_days INT UNSIGNED NULL COMMENT '交期快照',
    payment_terms VARCHAR(255) NULL COMMENT '付款条件快照',
    historical_score DECIMAL(5,2) NULL COMMENT '历史表现得分',
    composite_score DECIMAL(8,3) NULL COMMENT '综合比较得分',
    rank_no SMALLINT UNSIGNED NULL COMMENT '排序名次',
    selection_flag TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否选中该报价行',
    note VARCHAR(1000) NULL COMMENT '比较备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_comparison_quote_item (comparison_id, quote_id, rfq_item_id),
    KEY idx_comparison_item_rank (comparison_id, rfq_item_id, rank_no),
    KEY idx_comparison_item_supplier (supplier_id, rfq_item_id),
    CONSTRAINT fk_comparison_item_comparison FOREIGN KEY (comparison_id) REFERENCES quote_comparisons (id),
    CONSTRAINT fk_comparison_item_quote FOREIGN KEY (quote_id) REFERENCES supplier_quotes (id),
    CONSTRAINT fk_comparison_item_rfq_item FOREIGN KEY (rfq_item_id) REFERENCES rfq_items (id),
    CONSTRAINT fk_comparison_item_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT chk_comparison_item_price CHECK (quoted_unit_price >= 0 AND (total_amount IS NULL OR total_amount >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='报价比较明细';

CREATE TABLE purchase_orders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    po_no VARCHAR(32) NOT NULL COMMENT '采购订单业务编号',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    source_comparison_id BIGINT UNSIGNED NULL COMMENT '来源报价比较 ID',
    source_quote_id BIGINT UNSIGNED NULL COMMENT '来源报价 ID',
    source_request_id BIGINT UNSIGNED NULL COMMENT '来源采购申请 ID',
    department_id BIGINT UNSIGNED NULL COMMENT '下单部门 ID',
    buyer_id BIGINT UNSIGNED NOT NULL COMMENT '采购员用户 ID',
    order_amount DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '订单含税或未税总金额，口径由系统统一',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '订单币种',
    delivery_address VARCHAR(500) NULL COMMENT '收货地址',
    order_date DATE NULL COMMENT '正式下单日期，草稿时为空',
    expected_arrival_date DATE NULL COMMENT '期望到货日期',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、APPROVING、APPROVED、ORDERED、PARTIAL、COMPLETED、CANCELLED',
    supplier_confirmed_at DATETIME(3) NULL COMMENT '供应商确认时间',
    approved_at DATETIME(3) NULL COMMENT '审批通过时间',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    cancel_reason VARCHAR(1000) NULL COMMENT '取消原因',
    note VARCHAR(1000) NULL COMMENT '订单备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_purchase_order_no (po_no),
    KEY idx_po_supplier_status (supplier_id, status),
    KEY idx_po_buyer_status (buyer_id, status),
    KEY idx_po_department_status (department_id, status),
    KEY idx_po_expected_status (expected_arrival_date, status),
    CONSTRAINT fk_po_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_po_comparison FOREIGN KEY (source_comparison_id) REFERENCES quote_comparisons (id),
    CONSTRAINT fk_po_quote FOREIGN KEY (source_quote_id) REFERENCES supplier_quotes (id),
    CONSTRAINT fk_po_request FOREIGN KEY (source_request_id) REFERENCES purchase_requests (id),
    CONSTRAINT fk_po_department FOREIGN KEY (department_id) REFERENCES sys_departments (id),
    CONSTRAINT fk_po_buyer FOREIGN KEY (buyer_id) REFERENCES sys_users (id),
    CONSTRAINT chk_po_amount CHECK (order_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购订单主单';

CREATE TABLE purchase_order_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    supplier_product_id BIGINT UNSIGNED NULL COMMENT '供应商产品关联记录 ID',
    source_quote_item_id BIGINT UNSIGNED NULL COMMENT '来源报价明细 ID',
    product_name_snapshot VARCHAR(255) NOT NULL COMMENT '下单时产品名称快照',
    supplier_model_snapshot VARCHAR(128) NULL COMMENT '下单时供应商型号快照',
    order_quantity DECIMAL(18,6) NOT NULL COMMENT '订购数量',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '订购单位 ID',
    unit_price DECIMAL(18,6) NOT NULL COMMENT '订单单价',
    tax_rate DECIMAL(5,2) NULL COMMENT '税率',
    planned_arrival_date DATE NULL COMMENT '计划到货日期',
    received_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '累计到货数量',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、PARTIAL、FULFILLED、CANCELLED',
    note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_po_item_line (po_id, line_no),
    KEY idx_po_item_product_status (product_id, status),
    KEY idx_po_item_arrival_status (planned_arrival_date, status),
    CONSTRAINT fk_po_item_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_po_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_po_item_supplier_product FOREIGN KEY (supplier_product_id) REFERENCES supplier_products (id),
    CONSTRAINT fk_po_item_quote_item FOREIGN KEY (source_quote_item_id) REFERENCES supplier_quote_items (id),
    CONSTRAINT fk_po_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_po_item_quantity CHECK (order_quantity > 0 AND received_quantity >= 0 AND received_quantity <= order_quantity),
    CONSTRAINT chk_po_item_price CHECK (unit_price >= 0),
    CONSTRAINT chk_po_item_tax CHECK (tax_rate IS NULL OR tax_rate BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购订单明细';

CREATE TABLE purchase_order_approvals (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID',
    sequence_no SMALLINT UNSIGNED NOT NULL COMMENT '审批顺序',
    node_code VARCHAR(64) NOT NULL COMMENT '审批节点编码',
    node_name VARCHAR(128) NOT NULL COMMENT '审批节点名称',
    approver_id BIGINT UNSIGNED NULL COMMENT '实际审批人',
    action VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、APPROVED、REJECTED、RETURNED、SKIPPED',
    opinion VARCHAR(2000) NULL COMMENT '审批意见',
    acted_at DATETIME(3) NULL COMMENT '审批动作时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_po_approval_sequence (po_id, sequence_no),
    KEY idx_po_approval_pending (approver_id, action),
    CONSTRAINT fk_po_approval_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_po_approval_user FOREIGN KEY (approver_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购订单审批记录';

CREATE TABLE purchase_order_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID',
    event_type VARCHAR(32) NOT NULL COMMENT 'CONFIRMED、SHIPPED、DELAYED、PARTIAL_RECEIVED、COMPLETED、CANCELLED',
    event_time DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '事件发生时间',
    operator_id BIGINT UNSIGNED NULL COMMENT '操作人，系统事件可为空',
    from_status VARCHAR(20) NULL COMMENT '变更前状态',
    to_status VARCHAR(20) NULL COMMENT '变更后状态',
    event_note VARCHAR(2000) NULL COMMENT '事件说明',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录时间',
    PRIMARY KEY (id),
    KEY idx_po_event_time (po_id, event_time),
    KEY idx_po_event_type (event_type, event_time),
    CONSTRAINT fk_po_event_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_po_event_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购订单事件';

CREATE TABLE deliveries (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    delivery_no VARCHAR(32) NOT NULL COMMENT '到货单业务编号',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    shipment_date DATE NULL COMMENT '发货日期',
    expected_arrival_date DATE NULL COMMENT '预计到货日期',
    actual_arrival_date DATE NULL COMMENT '实际到货日期',
    logistics_company VARCHAR(128) NULL COMMENT '物流公司',
    tracking_no VARCHAR(128) NULL COMMENT '物流单号',
    status VARCHAR(20) NOT NULL DEFAULT 'IN_TRANSIT' COMMENT 'IN_TRANSIT、RECEIVED、INSPECTING、ACCEPTED、EXCEPTION、CANCELLED',
    received_by BIGINT UNSIGNED NULL COMMENT '收货人用户 ID',
    received_at DATETIME(3) NULL COMMENT '登记收货时间',
    note VARCHAR(1000) NULL COMMENT '到货备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_delivery_no (delivery_no),
    KEY idx_delivery_po_status (po_id, status),
    KEY idx_delivery_supplier_date (supplier_id, actual_arrival_date),
    KEY idx_delivery_expected_status (expected_arrival_date, status),
    CONSTRAINT fk_delivery_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_delivery_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_delivery_receiver FOREIGN KEY (received_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货记录';

CREATE TABLE delivery_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    delivery_id BIGINT UNSIGNED NOT NULL COMMENT '到货记录 ID',
    po_item_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单明细 ID',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '到货明细行号',
    batch_no VARCHAR(128) NULL COMMENT '批次号',
    package_spec VARCHAR(255) NULL COMMENT '实际包装规格',
    planned_quantity DECIMAL(18,6) NOT NULL COMMENT '本次计划到货数量',
    actual_quantity DECIMAL(18,6) NOT NULL COMMENT '本次实际到货数量',
    short_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '本次短交数量',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '到货单位 ID',
    production_date DATE NULL COMMENT '生产日期',
    expiry_date DATE NULL COMMENT '失效日期',
    document_complete TINYINT(1) NOT NULL DEFAULT 0 COMMENT '随货文件是否齐全',
    note VARCHAR(1000) NULL COMMENT '到货明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_delivery_item_line (delivery_id, line_no),
    KEY idx_delivery_item_po_item (po_item_id, product_id),
    KEY idx_delivery_item_batch (product_id, batch_no),
    CONSTRAINT fk_delivery_item_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries (id),
    CONSTRAINT fk_delivery_item_po_item FOREIGN KEY (po_item_id) REFERENCES purchase_order_items (id),
    CONSTRAINT fk_delivery_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_delivery_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_delivery_item_quantity CHECK (planned_quantity >= 0 AND actual_quantity >= 0 AND short_quantity >= 0 AND short_quantity <= planned_quantity),
    CONSTRAINT chk_delivery_item_dates CHECK (production_date IS NULL OR expiry_date IS NULL OR production_date <= expiry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货明细';

CREATE TABLE quality_acceptances (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    acceptance_no VARCHAR(32) NOT NULL COMMENT '验收单业务编号',
    delivery_id BIGINT UNSIGNED NOT NULL COMMENT '到货记录 ID',
    inspector_id BIGINT UNSIGNED NOT NULL COMMENT '验收人用户 ID',
    result VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、PASSED、PARTIAL、FAILED、REINSPECTION',
    inspection_time DATETIME(3) NULL COMMENT '验收时间',
    test_result JSON NULL COMMENT '检测结果结构化数据',
    certificate_complete TINYINT(1) NOT NULL DEFAULT 0 COMMENT '检测/合格证文件是否齐全',
    report_file_id BIGINT UNSIGNED NULL COMMENT '验收报告文件 ID',
    conclusion VARCHAR(2000) NULL COMMENT '验收结论',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_acceptance_no (acceptance_no),
    KEY idx_acceptance_delivery_result (delivery_id, result),
    KEY idx_acceptance_inspector_time (inspector_id, inspection_time),
    CONSTRAINT fk_acceptance_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries (id),
    CONSTRAINT fk_acceptance_inspector FOREIGN KEY (inspector_id) REFERENCES sys_users (id),
    CONSTRAINT fk_acceptance_report_file FOREIGN KEY (report_file_id) REFERENCES sys_files (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货验收';

CREATE TABLE finance_reconciliations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    reconciliation_no VARCHAR(32) NOT NULL COMMENT '对账单业务编号',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID，一张订单只允许一张对账单',
    supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID 快照关联',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '结算币种',
    total_amount DECIMAL(18,6) NOT NULL COMMENT '对账应付总额',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、CONFIRMED、DISPUTED、CLOSED、CANCELLED',
    created_by BIGINT UNSIGNED NOT NULL COMMENT '创建人用户 ID',
    confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间',
    closed_at DATETIME(3) NULL COMMENT '结算关闭时间',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    cancel_reason VARCHAR(1000) NULL COMMENT '取消原因',
    note VARCHAR(1000) NULL COMMENT '对账备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_finance_reconciliation_no (reconciliation_no), UNIQUE KEY uk_finance_reconciliation_po (po_id),
    KEY idx_finance_reconciliation_supplier_status (supplier_id, status), KEY idx_finance_reconciliation_status_time (status, created_at),
    CONSTRAINT fk_finance_reconciliation_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_finance_reconciliation_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_finance_reconciliation_creator FOREIGN KEY (created_by) REFERENCES sys_users (id),
    CONSTRAINT fk_finance_reconciliation_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_finance_reconciliation_amount CHECK (total_amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='财务对账主单';

CREATE TABLE finance_invoices (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    invoice_no VARCHAR(32) NOT NULL COMMENT '系统发票记录编号', reconciliation_id BIGINT UNSIGNED NOT NULL COMMENT '对账单 ID',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    invoice_code VARCHAR(32) NULL COMMENT '发票代码，电子票可能为空', invoice_number VARCHAR(64) NOT NULL COMMENT '发票号码', invoice_date DATE NOT NULL COMMENT '开票日期',
    amount_excl_tax DECIMAL(18,6) NOT NULL COMMENT '不含税金额', tax_amount DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '税额', amount_incl_tax DECIMAL(18,6) NOT NULL COMMENT '价税合计',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '发票币种', status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、VERIFIED、REJECTED、VOIDED',
    source_file_id BIGINT UNSIGNED NULL COMMENT '发票附件文件 ID', submitted_by BIGINT UNSIGNED NOT NULL COMMENT '录入人用户 ID', verified_by BIGINT UNSIGNED NULL COMMENT '核验人用户 ID',
    verified_at DATETIME(3) NULL COMMENT '核验时间', reject_reason VARCHAR(1000) NULL COMMENT '驳回原因', note VARCHAR(1000) NULL COMMENT '发票备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_finance_invoice_no (invoice_no), UNIQUE KEY uk_finance_invoice_supplier_number (supplier_id, invoice_number),
    KEY idx_finance_invoice_reconciliation_status (reconciliation_id, status), KEY idx_finance_invoice_supplier_date (supplier_id, invoice_date),
    CONSTRAINT fk_finance_invoice_reconciliation FOREIGN KEY (reconciliation_id) REFERENCES finance_reconciliations (id), CONSTRAINT fk_finance_invoice_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_finance_invoice_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_finance_invoice_file FOREIGN KEY (source_file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_finance_invoice_submitter FOREIGN KEY (submitted_by) REFERENCES sys_users (id), CONSTRAINT fk_finance_invoice_verifier FOREIGN KEY (verified_by) REFERENCES sys_users (id),
    CONSTRAINT chk_finance_invoice_amounts CHECK (amount_excl_tax >= 0 AND tax_amount >= 0 AND amount_incl_tax >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商发票记录';

CREATE TABLE finance_payments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', payment_no VARCHAR(32) NOT NULL COMMENT '付款单业务编号',
    reconciliation_id BIGINT UNSIGNED NOT NULL COMMENT '对账单 ID', po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID',
    amount DECIMAL(18,6) NOT NULL COMMENT '本次付款金额', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '付款币种', payment_method VARCHAR(32) NOT NULL COMMENT 'BANK_TRANSFER、CASH、OTHER',
    status VARCHAR(20) NOT NULL DEFAULT 'REQUESTED' COMMENT 'REQUESTED、APPROVED、PAID、REJECTED、CANCELLED', requested_by BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID', paid_by BIGINT UNSIGNED NULL COMMENT '实际付款操作人用户 ID', approved_at DATETIME(3) NULL COMMENT '审批时间', paid_at DATETIME(3) NULL COMMENT '付款时间',
    transaction_ref VARCHAR(128) NULL COMMENT '银行流水号或外部支付流水号', reject_reason VARCHAR(1000) NULL COMMENT '驳回原因', note VARCHAR(1000) NULL COMMENT '付款备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_finance_payment_no (payment_no), UNIQUE KEY uk_finance_payment_transaction_ref (transaction_ref), KEY idx_finance_payment_reconciliation_status (reconciliation_id, status), KEY idx_finance_payment_supplier_date (supplier_id, paid_at),
    CONSTRAINT fk_finance_payment_reconciliation FOREIGN KEY (reconciliation_id) REFERENCES finance_reconciliations (id), CONSTRAINT fk_finance_payment_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_finance_payment_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_finance_payment_requester FOREIGN KEY (requested_by) REFERENCES sys_users (id),
    CONSTRAINT fk_finance_payment_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id), CONSTRAINT fk_finance_payment_payer FOREIGN KEY (paid_by) REFERENCES sys_users (id), CONSTRAINT chk_finance_payment_amount CHECK (amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='付款申请和付款记录';

CREATE TABLE finance_settlements (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', settlement_no VARCHAR(32) NOT NULL COMMENT '结算单业务编号', reconciliation_id BIGINT UNSIGNED NOT NULL COMMENT '对账单 ID，一张对账单只允许一张结算单',
    po_id BIGINT UNSIGNED NOT NULL COMMENT '采购订单 ID', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '供应商 ID', settlement_amount DECIMAL(18,6) NOT NULL COMMENT '结算金额', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '结算币种',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、CONFIRMED、CANCELLED', created_by BIGINT UNSIGNED NOT NULL COMMENT '创建人用户 ID', confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间', cancelled_at DATETIME(3) NULL COMMENT '取消时间', cancel_reason VARCHAR(1000) NULL COMMENT '取消原因', note VARCHAR(1000) NULL COMMENT '结算备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_finance_settlement_no (settlement_no), UNIQUE KEY uk_finance_settlement_reconciliation (reconciliation_id), KEY idx_finance_settlement_supplier_status (supplier_id, status),
    CONSTRAINT fk_finance_settlement_reconciliation FOREIGN KEY (reconciliation_id) REFERENCES finance_reconciliations (id), CONSTRAINT fk_finance_settlement_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_finance_settlement_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_finance_settlement_creator FOREIGN KEY (created_by) REFERENCES sys_users (id), CONSTRAINT fk_finance_settlement_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_finance_settlement_amount CHECK (settlement_amount > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购结算单';

CREATE TABLE inventory_return_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', return_no VARCHAR(32) NOT NULL COMMENT '退货单业务编号', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '退回供应商 ID', po_id BIGINT UNSIGNED NULL COMMENT '来源采购订单 ID', delivery_id BIGINT UNSIGNED NULL COMMENT '来源到货单 ID', applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID', reason VARCHAR(1000) NOT NULL COMMENT '退货原因', status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED', approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID', approved_at DATETIME(3) NULL COMMENT '审批时间', rejected_at DATETIME(3) NULL COMMENT '驳回时间', reject_reason VARCHAR(1000) NULL COMMENT '驳回原因', cancelled_at DATETIME(3) NULL COMMENT '取消时间', completed_at DATETIME(3) NULL COMMENT '完成时间', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_return_no (return_no), KEY idx_inventory_return_supplier_status (supplier_id, status), KEY idx_inventory_return_source (po_id, delivery_id),
    CONSTRAINT fk_inventory_return_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_inventory_return_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id), CONSTRAINT fk_inventory_return_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries (id), CONSTRAINT fk_inventory_return_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id), CONSTRAINT fk_inventory_return_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商退货申请';

CREATE TABLE inventory_return_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', return_request_id BIGINT UNSIGNED NOT NULL COMMENT '退货申请 ID', line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号', product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID', location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '库存批次 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID', requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请退货数量', returned_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际退货数量', status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、RETURNED', note VARCHAR(1000) NULL COMMENT '明细备注', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_return_item_line (return_request_id, line_no), KEY idx_inventory_return_item_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_return_item_request FOREIGN KEY (return_request_id) REFERENCES inventory_return_requests (id), CONSTRAINT fk_inventory_return_item_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_inventory_return_item_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_return_item_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id), CONSTRAINT fk_inventory_return_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT fk_inventory_return_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id), CONSTRAINT chk_inventory_return_item_quantity CHECK (requested_quantity > 0 AND returned_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商退货明细';

CREATE TABLE replenishment_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', replenishment_no VARCHAR(32) NOT NULL COMMENT '补货申请业务编号', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '补货供应商 ID', source_po_id BIGINT UNSIGNED NULL COMMENT '来源采购订单 ID', source_delivery_id BIGINT UNSIGNED NULL COMMENT '来源到货单 ID', applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID', reason VARCHAR(1000) NOT NULL COMMENT '补货原因', status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED', fulfillment_po_id BIGINT UNSIGNED NULL COMMENT '实际执行补货的采购订单 ID', approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID', approved_at DATETIME(3) NULL COMMENT '审批时间', rejected_at DATETIME(3) NULL COMMENT '驳回时间', reject_reason VARCHAR(1000) NULL COMMENT '驳回原因', cancelled_at DATETIME(3) NULL COMMENT '取消时间', completed_at DATETIME(3) NULL COMMENT '完成时间', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_replenishment_no (replenishment_no), KEY idx_replenishment_supplier_status (supplier_id, status), KEY idx_replenishment_source (source_po_id, source_delivery_id),
    CONSTRAINT fk_replenishment_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id), CONSTRAINT fk_replenishment_source_po FOREIGN KEY (source_po_id) REFERENCES purchase_orders (id), CONSTRAINT fk_replenishment_source_delivery FOREIGN KEY (source_delivery_id) REFERENCES deliveries (id), CONSTRAINT fk_replenishment_fulfillment_po FOREIGN KEY (fulfillment_po_id) REFERENCES purchase_orders (id), CONSTRAINT fk_replenishment_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id), CONSTRAINT fk_replenishment_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商补货申请';

CREATE TABLE replenishment_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', replenishment_request_id BIGINT UNSIGNED NOT NULL COMMENT '补货申请 ID', line_no SMALLINT UNSIGNED NOT NULL COMMENT '明细行号', product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID', requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请补货数量', expected_date DATE NULL COMMENT '期望到货日期', status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、FULFILLED', note VARCHAR(1000) NULL COMMENT '明细备注', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_replenishment_item_line (replenishment_request_id, line_no), KEY idx_replenishment_item_product (product_id, status),
    CONSTRAINT fk_replenishment_item_request FOREIGN KEY (replenishment_request_id) REFERENCES replenishment_requests (id), CONSTRAINT fk_replenishment_item_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_replenishment_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id), CONSTRAINT chk_replenishment_item_quantity CHECK (requested_quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商补货明细';

CREATE TABLE supplier_portal_accounts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', user_id BIGINT UNSIGNED NOT NULL COMMENT '系统用户 ID', supplier_id BIGINT UNSIGNED NOT NULL COMMENT '绑定供应商 ID', status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、INACTIVE', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间', updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id), UNIQUE KEY uk_supplier_portal_user (user_id), UNIQUE KEY uk_supplier_portal_supplier_user (supplier_id, user_id), KEY idx_supplier_portal_supplier_status (supplier_id, status),
    CONSTRAINT fk_supplier_portal_user FOREIGN KEY (user_id) REFERENCES sys_users (id), CONSTRAINT fk_supplier_portal_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商门户账号绑定';

CREATE TABLE warehouses (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    warehouse_code VARCHAR(64) NOT NULL COMMENT '仓库编码',
    warehouse_name VARCHAR(128) NOT NULL COMMENT '仓库名称',
    region VARCHAR(128) NULL COMMENT '所属地区',
    address VARCHAR(500) NULL COMMENT '仓库地址',
    manager_id BIGINT UNSIGNED NULL COMMENT '仓库负责人用户 ID',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、INACTIVE',
    note VARCHAR(1000) NULL COMMENT '备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_warehouse_code (warehouse_code),
    KEY idx_warehouse_status_name (status, warehouse_name),
    CONSTRAINT fk_warehouse_manager FOREIGN KEY (manager_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='仓库主数据';

CREATE TABLE warehouse_locations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID',
    location_code VARCHAR(64) NOT NULL COMMENT '库位编码',
    location_name VARCHAR(128) NOT NULL COMMENT '库位名称',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、INACTIVE',
    note VARCHAR(500) NULL COMMENT '备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_location_warehouse_code (warehouse_id, location_code),
    KEY idx_location_warehouse_status (warehouse_id, status),
    CONSTRAINT fk_location_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='仓库库位';

CREATE TABLE inventory_batches (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    batch_no VARCHAR(128) NOT NULL COMMENT '批次号，无实物批次时由系统生成来源批次号',
    supplier_id BIGINT UNSIGNED NULL COMMENT '供应商 ID',
    source_delivery_id BIGINT UNSIGNED NULL COMMENT '来源到货单 ID',
    production_date DATE NULL COMMENT '生产日期',
    expiry_date DATE NULL COMMENT '失效日期',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、BLOCKED、EXPIRED',
    note VARCHAR(1000) NULL COMMENT '批次备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_batch_source (product_id, batch_no, source_delivery_id),
    KEY idx_inventory_batch_expiry (product_id, expiry_date, status),
    CONSTRAINT fk_inventory_batch_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_batch_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_inventory_batch_delivery FOREIGN KEY (source_delivery_id) REFERENCES deliveries (id),
    CONSTRAINT chk_inventory_batch_dates CHECK (production_date IS NULL OR expiry_date IS NULL OR production_date <= expiry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存批次';

CREATE TABLE inventory_balances (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID',
    location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '库存单位 ID',
    quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '可用库存数量',
    locked_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '锁定库存数量',
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE' COMMENT 'AVAILABLE、BLOCKED',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_balance_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    KEY idx_inventory_balance_product (product_id, warehouse_id, status),
    KEY idx_inventory_balance_batch (batch_id, status),
    CONSTRAINT fk_inventory_balance_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_balance_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_balance_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_balance_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_balance_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_balance_quantity CHECK (quantity >= 0 AND locked_quantity >= 0 AND locked_quantity <= quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存余额';

CREATE TABLE inventory_balance_status_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    balance_id BIGINT UNSIGNED NOT NULL COMMENT '库存余额 ID',
    previous_status VARCHAR(20) NOT NULL COMMENT '变更前状态',
    new_status VARCHAR(20) NOT NULL COMMENT '变更后状态',
    reason VARCHAR(1000) NOT NULL COMMENT '冻结或解冻原因',
    operator_id BIGINT UNSIGNED NOT NULL COMMENT '操作人用户 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '操作时间',
    PRIMARY KEY (id),
    KEY idx_inventory_balance_status_log_balance_time (balance_id, created_at),
    KEY idx_inventory_balance_status_log_operator_time (operator_id, created_at),
    CONSTRAINT fk_inventory_balance_status_log_balance FOREIGN KEY (balance_id) REFERENCES inventory_balances (id),
    CONSTRAINT fk_inventory_balance_status_log_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存状态变更记录';

CREATE TABLE inventory_transactions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    transaction_no VARCHAR(32) NOT NULL COMMENT '库存流水编号',
    transaction_type VARCHAR(20) NOT NULL COMMENT 'INBOUND、OUTBOUND、ADJUSTMENT',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID',
    location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '库存单位 ID',
    quantity DECIMAL(18,6) NOT NULL COMMENT '本次变动数量，出库时由服务层记录方向',
    delivery_item_id BIGINT UNSIGNED NULL COMMENT '来源到货明细，入库幂等键',
    source_type VARCHAR(32) NULL COMMENT '来源类型',
    source_id BIGINT UNSIGNED NULL COMMENT '来源业务 ID',
    operator_id BIGINT UNSIGNED NOT NULL COMMENT '操作人用户 ID',
    note VARCHAR(1000) NULL COMMENT '流水备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '发生时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_transaction_no (transaction_no),
    UNIQUE KEY uk_inventory_transaction_delivery_item (delivery_item_id),
    KEY idx_inventory_transaction_product_time (product_id, created_at),
    KEY idx_inventory_transaction_source (source_type, source_id),
    CONSTRAINT fk_inventory_transaction_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_transaction_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_transaction_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_transaction_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_transaction_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT fk_inventory_transaction_delivery_item FOREIGN KEY (delivery_item_id) REFERENCES delivery_items (id),
    CONSTRAINT fk_inventory_transaction_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id),
    CONSTRAINT chk_inventory_transaction_quantity CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存流水';

CREATE TABLE inventory_cost_layers (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', source_transaction_id BIGINT UNSIGNED NOT NULL COMMENT '来源入库流水 ID', warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID', location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID', product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID', unit_cost DECIMAL(18,6) NOT NULL COMMENT '单位成本', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '成本币种', original_quantity DECIMAL(18,6) NOT NULL COMMENT '原始数量', remaining_quantity DECIMAL(18,6) NOT NULL COMMENT '剩余数量', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_cost_layer_source (source_transaction_id), KEY idx_inventory_cost_layer_fifo (product_id, warehouse_id, location_id, unit_id, remaining_quantity, created_at), KEY idx_inventory_cost_layer_expiry (batch_id, remaining_quantity),
    CONSTRAINT fk_inventory_cost_layer_transaction FOREIGN KEY (source_transaction_id) REFERENCES inventory_transactions (id), CONSTRAINT fk_inventory_cost_layer_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_cost_layer_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id), CONSTRAINT fk_inventory_cost_layer_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_inventory_cost_layer_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT fk_inventory_cost_layer_unit FOREIGN KEY (unit_id) REFERENCES md_units (id), CONSTRAINT chk_inventory_cost_layer_quantity CHECK (original_quantity > 0 AND remaining_quantity >= 0 AND remaining_quantity <= original_quantity), CONSTRAINT chk_inventory_cost_layer_cost CHECK (unit_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存 FIFO 成本层';

CREATE TABLE inventory_cost_allocations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    transaction_id BIGINT UNSIGNED NOT NULL COMMENT '库存流水 ID',
    cost_layer_id BIGINT UNSIGNED NOT NULL COMMENT '来源成本层 ID',
    quantity DECIMAL(18,6) NOT NULL COMMENT '分摊数量',
    unit_cost DECIMAL(18,6) NOT NULL COMMENT '单位成本',
    total_cost DECIMAL(18,6) NOT NULL COMMENT '分摊总成本',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_cost_allocation_layer (transaction_id, cost_layer_id),
    KEY idx_inventory_cost_allocation_layer (cost_layer_id, created_at),
    CONSTRAINT fk_inventory_cost_allocation_transaction FOREIGN KEY (transaction_id) REFERENCES inventory_transactions (id),
    CONSTRAINT fk_inventory_cost_allocation_layer FOREIGN KEY (cost_layer_id) REFERENCES inventory_cost_layers (id),
    CONSTRAINT chk_inventory_cost_allocation_amount CHECK (quantity > 0 AND unit_cost >= 0 AND total_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='普通库存出库成本分摊';

CREATE TABLE inventory_fifo_outbound_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', request_no VARCHAR(64) NOT NULL COMMENT '客户端幂等请求号', product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID', warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID', location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID', unit_id BIGINT UNSIGNED NOT NULL COMMENT '计量单位 ID', requested_quantity DECIMAL(18,6) NOT NULL COMMENT '请求出库数量', issued_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际出库数量', total_cost DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '汇总成本', currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '成本币种', status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED' COMMENT 'COMPLETED', operator_id BIGINT UNSIGNED NOT NULL COMMENT '操作人用户 ID', note VARCHAR(1000) NULL COMMENT '备注', created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_fifo_request_no (request_no), KEY idx_inventory_fifo_request_product_time (product_id, warehouse_id, location_id, created_at), CONSTRAINT fk_inventory_fifo_request_product FOREIGN KEY (product_id) REFERENCES md_products (id), CONSTRAINT fk_inventory_fifo_request_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id), CONSTRAINT fk_inventory_fifo_request_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id), CONSTRAINT fk_inventory_fifo_request_unit FOREIGN KEY (unit_id) REFERENCES md_units (id), CONSTRAINT fk_inventory_fifo_request_operator FOREIGN KEY (operator_id) REFERENCES sys_users (id), CONSTRAINT chk_inventory_fifo_request_quantity CHECK (requested_quantity > 0 AND issued_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='FIFO 出库请求';

CREATE TABLE inventory_fifo_outbound_allocations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键', request_id BIGINT UNSIGNED NOT NULL COMMENT 'FIFO 出库请求 ID', cost_layer_id BIGINT UNSIGNED NOT NULL COMMENT '成本层 ID', batch_id BIGINT UNSIGNED NOT NULL COMMENT '批次 ID', quantity DECIMAL(18,6) NOT NULL COMMENT '分摊数量', unit_cost DECIMAL(18,6) NOT NULL COMMENT '单位成本', total_cost DECIMAL(18,6) NOT NULL COMMENT '分摊成本',
    PRIMARY KEY (id), UNIQUE KEY uk_inventory_fifo_allocation_layer (request_id, cost_layer_id), KEY idx_inventory_fifo_allocation_batch (batch_id, request_id), CONSTRAINT fk_inventory_fifo_allocation_request FOREIGN KEY (request_id) REFERENCES inventory_fifo_outbound_requests (id), CONSTRAINT fk_inventory_fifo_allocation_layer FOREIGN KEY (cost_layer_id) REFERENCES inventory_cost_layers (id), CONSTRAINT fk_inventory_fifo_allocation_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id), CONSTRAINT chk_inventory_fifo_allocation_quantity CHECK (quantity > 0 AND unit_cost >= 0 AND total_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='FIFO 出库成本分摊';

CREATE TABLE inventory_issue_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    issue_no VARCHAR(32) NOT NULL COMMENT '领用单编号',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID',
    department_id BIGINT UNSIGNED NULL COMMENT '领用部门 ID',
    purpose VARCHAR(500) NOT NULL COMMENT '领用用途',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID',
    approved_at DATETIME(3) NULL COMMENT '审批时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间',
    reject_reason VARCHAR(1000) NULL COMMENT '驳回原因',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    completed_at DATETIME(3) NULL COMMENT '出库完成时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_issue_no (issue_no),
    KEY idx_inventory_issue_applicant_status (applicant_id, status),
    KEY idx_inventory_issue_status_time (status, created_at),
    CONSTRAINT fk_inventory_issue_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_inventory_issue_department FOREIGN KEY (department_id) REFERENCES sys_departments (id),
    CONSTRAINT fk_inventory_issue_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存领用申请';

CREATE TABLE inventory_issue_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    issue_request_id BIGINT UNSIGNED NOT NULL COMMENT '领用申请 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '行号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '仓库 ID',
    location_id BIGINT UNSIGNED NOT NULL COMMENT '库位 ID',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '库存批次 ID',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '领用单位 ID',
    requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请数量',
    issued_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际出库数量',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、ISSUED、CANCELLED',
    note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_issue_item_line (issue_request_id, line_no),
    KEY idx_inventory_issue_item_slot (warehouse_id, location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_issue_item_request FOREIGN KEY (issue_request_id) REFERENCES inventory_issue_requests (id),
    CONSTRAINT fk_inventory_issue_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_issue_item_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_issue_item_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_issue_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_issue_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_issue_item_quantity CHECK (requested_quantity > 0 AND issued_quantity >= 0 AND issued_quantity <= requested_quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存领用申请明细';

CREATE TABLE inventory_transfer_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    transfer_no VARCHAR(32) NOT NULL COMMENT '调拨单编号',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '申请人用户 ID',
    purpose VARCHAR(500) NOT NULL COMMENT '调拨用途',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID',
    approved_at DATETIME(3) NULL COMMENT '审批时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间',
    reject_reason VARCHAR(1000) NULL COMMENT '驳回原因',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    completed_at DATETIME(3) NULL COMMENT '调拨完成时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_transfer_no (transfer_no),
    KEY idx_inventory_transfer_applicant_status (applicant_id, status),
    KEY idx_inventory_transfer_status_time (status, created_at),
    CONSTRAINT fk_inventory_transfer_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_inventory_transfer_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存调拨申请';

CREATE TABLE inventory_transfer_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    transfer_request_id BIGINT UNSIGNED NOT NULL COMMENT '调拨申请 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '行号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    source_warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '源仓库 ID',
    source_location_id BIGINT UNSIGNED NOT NULL COMMENT '源库位 ID',
    target_warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '目标仓库 ID',
    target_location_id BIGINT UNSIGNED NOT NULL COMMENT '目标库位 ID',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '库存批次 ID',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '调拨单位 ID',
    requested_quantity DECIMAL(18,6) NOT NULL COMMENT '申请调拨数量',
    transferred_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '实际调拨数量',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、TRANSFERRED、CANCELLED',
    note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_transfer_item_line (transfer_request_id, line_no),
    KEY idx_inventory_transfer_item_source (source_warehouse_id, source_location_id, product_id, batch_id, unit_id),
    KEY idx_inventory_transfer_item_target (target_warehouse_id, target_location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_transfer_item_request FOREIGN KEY (transfer_request_id) REFERENCES inventory_transfer_requests (id),
    CONSTRAINT fk_inventory_transfer_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_transfer_item_source_warehouse FOREIGN KEY (source_warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_transfer_item_source_location FOREIGN KEY (source_location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_transfer_item_target_warehouse FOREIGN KEY (target_warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_transfer_item_target_location FOREIGN KEY (target_location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_transfer_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_transfer_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_transfer_item_location CHECK (NOT (source_warehouse_id = target_warehouse_id AND source_location_id = target_location_id)),
    CONSTRAINT chk_inventory_transfer_item_quantity CHECK (requested_quantity > 0 AND transferred_quantity >= 0 AND transferred_quantity <= requested_quantity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存调拨申请明细';

CREATE TABLE inventory_stocktake_requests (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    stocktake_no VARCHAR(32) NOT NULL COMMENT '盘点单编号',
    applicant_id BIGINT UNSIGNED NOT NULL COMMENT '盘点申请人用户 ID',
    warehouse_id BIGINT UNSIGNED NOT NULL COMMENT '盘点仓库 ID',
    location_id BIGINT UNSIGNED NULL COMMENT '指定盘点库位 ID，空表示仓库范围',
    purpose VARCHAR(500) NOT NULL COMMENT '盘点原因',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT、SUBMITTED、APPROVED、REJECTED、CANCELLED、COMPLETED',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批人用户 ID',
    approved_at DATETIME(3) NULL COMMENT '审批时间',
    rejected_at DATETIME(3) NULL COMMENT '驳回时间',
    reject_reason VARCHAR(1000) NULL COMMENT '驳回原因',
    cancelled_at DATETIME(3) NULL COMMENT '取消时间',
    completed_at DATETIME(3) NULL COMMENT '盘点完成时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_stocktake_no (stocktake_no),
    KEY idx_inventory_stocktake_warehouse_status (warehouse_id, status),
    KEY idx_inventory_stocktake_applicant_status (applicant_id, status),
    KEY idx_inventory_stocktake_status_time (status, created_at),
    CONSTRAINT fk_inventory_stocktake_applicant FOREIGN KEY (applicant_id) REFERENCES sys_users (id),
    CONSTRAINT fk_inventory_stocktake_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses (id),
    CONSTRAINT fk_inventory_stocktake_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_stocktake_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存盘点申请';

CREATE TABLE inventory_stocktake_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    stocktake_request_id BIGINT UNSIGNED NOT NULL COMMENT '盘点申请 ID',
    line_no SMALLINT UNSIGNED NOT NULL COMMENT '行号',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    location_id BIGINT UNSIGNED NOT NULL COMMENT '盘点库位 ID',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '库存批次 ID',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '盘点单位 ID',
    book_quantity DECIMAL(18,6) NOT NULL COMMENT '创建盘点单时的账面数量',
    counted_quantity DECIMAL(18,6) NOT NULL COMMENT '实盘数量',
    difference_quantity DECIMAL(18,6) NOT NULL DEFAULT 0 COMMENT '差异数量，实盘减账面',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、ADJUSTED',
    note VARCHAR(1000) NULL COMMENT '明细备注',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_inventory_stocktake_item_line (stocktake_request_id, line_no),
    KEY idx_inventory_stocktake_item_slot (location_id, product_id, batch_id, unit_id),
    CONSTRAINT fk_inventory_stocktake_item_request FOREIGN KEY (stocktake_request_id) REFERENCES inventory_stocktake_requests (id),
    CONSTRAINT fk_inventory_stocktake_item_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_inventory_stocktake_item_location FOREIGN KEY (location_id) REFERENCES warehouse_locations (id),
    CONSTRAINT fk_inventory_stocktake_item_batch FOREIGN KEY (batch_id) REFERENCES inventory_batches (id),
    CONSTRAINT fk_inventory_stocktake_item_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT chk_inventory_stocktake_item_quantity CHECK (book_quantity >= 0 AND counted_quantity >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存盘点明细';

CREATE TABLE operation_exceptions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    exception_no VARCHAR(32) NOT NULL COMMENT '异常编号',
    exception_type VARCHAR(32) NOT NULL COMMENT 'SHORT_DELIVERY、QUALITY、DOCUMENT、OVERDUE、OTHER',
    source_type VARCHAR(32) NOT NULL COMMENT '来源业务类型',
    source_id BIGINT UNSIGNED NOT NULL COMMENT '来源业务 ID，具体外键由下列专用字段保证',
    po_id BIGINT UNSIGNED NULL COMMENT '关联采购订单 ID',
    delivery_id BIGINT UNSIGNED NULL COMMENT '关联到货记录 ID',
    delivery_item_id BIGINT UNSIGNED NULL COMMENT '关联到货明细 ID',
    severity VARCHAR(20) NOT NULL DEFAULT 'MEDIUM' COMMENT 'LOW、MEDIUM、HIGH、CRITICAL',
    description TEXT NOT NULL COMMENT '异常描述',
    responsible_department_id BIGINT UNSIGNED NULL COMMENT '责任部门 ID',
    owner_id BIGINT UNSIGNED NULL COMMENT '异常负责人用户 ID',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、PROCESSING、RESOLVED、CLOSED、CANCELLED',
    due_at DATETIME(3) NULL COMMENT '处理期限',
    closed_by BIGINT UNSIGNED NULL COMMENT '关闭人用户 ID',
    closed_at DATETIME(3) NULL COMMENT '关闭时间',
    closing_note VARCHAR(2000) NULL COMMENT '关闭说明',
    active_dedupe_key VARCHAR(200) GENERATED ALWAYS AS (CASE WHEN status IN ('OPEN', 'PROCESSING', 'RESOLVED') THEN CONCAT(exception_type, ':' , source_type, ':' , source_id) ELSE NULL END) STORED,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_exception_no (exception_no),
    UNIQUE KEY uk_exception_active_dedupe (active_dedupe_key),
    KEY idx_exception_source (source_type, source_id),
    KEY idx_exception_status_due (status, due_at),
    KEY idx_exception_po_status (po_id, status),
    KEY idx_exception_owner_status (owner_id, status),
    CONSTRAINT fk_exception_po FOREIGN KEY (po_id) REFERENCES purchase_orders (id),
    CONSTRAINT fk_exception_delivery FOREIGN KEY (delivery_id) REFERENCES deliveries (id),
    CONSTRAINT fk_exception_delivery_item FOREIGN KEY (delivery_item_id) REFERENCES delivery_items (id),
    CONSTRAINT fk_exception_department FOREIGN KEY (responsible_department_id) REFERENCES sys_departments (id),
    CONSTRAINT fk_exception_owner FOREIGN KEY (owner_id) REFERENCES sys_users (id),
    CONSTRAINT fk_exception_closer FOREIGN KEY (closed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购运营异常';

CREATE TABLE operation_tasks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    exception_id BIGINT UNSIGNED NOT NULL COMMENT '来源异常 ID',
    title VARCHAR(255) NOT NULL COMMENT '任务标题',
    assignee_id BIGINT UNSIGNED NULL COMMENT '负责人用户 ID',
    priority VARCHAR(20) NOT NULL DEFAULT 'NORMAL' COMMENT 'LOW、NORMAL、HIGH、URGENT',
    due_at DATETIME(3) NULL COMMENT '任务截止时间',
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN、PROCESSING、COMPLETED、CANCELLED',
    completed_at DATETIME(3) NULL COMMENT '完成时间',
    completion_note VARCHAR(2000) NULL COMMENT '完成说明',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_task_exception_status (exception_id, status),
    KEY idx_task_assignee_status_due (assignee_id, status, due_at),
    CONSTRAINT fk_task_exception FOREIGN KEY (exception_id) REFERENCES operation_exceptions (id),
    CONSTRAINT fk_task_assignee FOREIGN KEY (assignee_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='异常处理任务';

CREATE TABLE operation_task_comments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    task_id BIGINT UNSIGNED NOT NULL COMMENT '任务 ID',
    commenter_id BIGINT UNSIGNED NOT NULL COMMENT '处理人用户 ID',
    content TEXT NOT NULL COMMENT '处理内容',
    attachment_file_id BIGINT UNSIGNED NULL COMMENT '附件文件 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录时间',
    PRIMARY KEY (id),
    KEY idx_task_comment_task_time (task_id, created_at),
    CONSTRAINT fk_task_comment_task FOREIGN KEY (task_id) REFERENCES operation_tasks (id),
    CONSTRAINT fk_task_comment_user FOREIGN KEY (commenter_id) REFERENCES sys_users (id),
    CONSTRAINT fk_task_comment_file FOREIGN KEY (attachment_file_id) REFERENCES sys_files (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务处理记录';

CREATE TABLE knowledge_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    file_id BIGINT UNSIGNED NOT NULL COMMENT '对应文件元数据 ID',
    title VARCHAR(255) NOT NULL COMMENT '文档标题',
    document_type VARCHAR(32) NOT NULL COMMENT 'TDS、SDS、COA、QUOTE、QUALIFICATION、OTHER',
    version_label VARCHAR(64) NULL COMMENT '文档版本号',
    source_name VARCHAR(255) NULL COMMENT '来源名称或来源系统',
    published_at DATE NULL COMMENT '发布日期',
    effective_from DATE NULL COMMENT '生效日期',
    expires_at DATE NULL COMMENT '业务有效期',
    chemical_id BIGINT UNSIGNED NULL COMMENT '关联化学品 ID',
    product_id BIGINT UNSIGNED NULL COMMENT '关联产品 ID',
    supplier_id BIGINT UNSIGNED NULL COMMENT '关联供应商 ID',
    confirmation_status VARCHAR(20) NOT NULL DEFAULT 'UNCONFIRMED' COMMENT 'UNCONFIRMED、CONFIRMED、REJECTED',
    confirmed_by BIGINT UNSIGNED NULL COMMENT '确认人用户 ID',
    confirmed_at DATETIME(3) NULL COMMENT '确认时间',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT '文档状态',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_knowledge_document_file (file_id),
    KEY idx_document_product_type (product_id, document_type, status),
    KEY idx_document_supplier_type (supplier_id, document_type, status),
    KEY idx_document_chemical_type (chemical_id, document_type, status),
    KEY idx_document_expiry (expires_at, confirmation_status),
    CONSTRAINT fk_document_file FOREIGN KEY (file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_document_chemical FOREIGN KEY (chemical_id) REFERENCES md_chemicals (id),
    CONSTRAINT fk_document_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_document_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_document_confirmer FOREIGN KEY (confirmed_by) REFERENCES sys_users (id),
    CONSTRAINT chk_document_dates CHECK (effective_from IS NULL OR expires_at IS NULL OR effective_from <= expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库文档';

CREATE TABLE knowledge_document_chunks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    document_id BIGINT UNSIGNED NOT NULL COMMENT '知识库文档 ID',
    chunk_no INT UNSIGNED NOT NULL COMMENT '文档片段顺序号',
    page_no INT UNSIGNED NULL COMMENT '来源页码',
    section_path VARCHAR(500) NULL COMMENT '章节路径',
    content LONGTEXT NOT NULL COMMENT '片段文本',
    extracted_fields JSON NULL COMMENT '从片段提取的结构化字段',
    source_locator VARCHAR(255) NULL COMMENT '来源定位信息，如段落或表格单元格',
    confirmation_status VARCHAR(20) NOT NULL DEFAULT 'UNCONFIRMED' COMMENT '片段内容确认状态',
    vector_ref VARCHAR(255) NULL COMMENT '外部向量库记录 ID，MVP 可为空',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_document_chunk_no (document_id, chunk_no),
    KEY idx_chunk_document_page (document_id, page_no),
    KEY idx_chunk_vector_ref (vector_ref),
    FULLTEXT KEY ft_chunk_content (content),
    CONSTRAINT fk_chunk_document FOREIGN KEY (document_id) REFERENCES knowledge_documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库文档片段';

CREATE TABLE market_price_records (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '产品 ID',
    supplier_id BIGINT UNSIGNED NULL COMMENT '供应商 ID，公开行情可为空',
    quote_date DATE NOT NULL COMMENT '价格日期',
    quantity_from DECIMAL(18,6) NULL COMMENT '数量区间下限',
    quantity_to DECIMAL(18,6) NULL COMMENT '数量区间上限',
    unit_id BIGINT UNSIGNED NOT NULL COMMENT '价格单位',
    price DECIMAL(18,6) NOT NULL COMMENT '单价',
    currency_code CHAR(3) NOT NULL DEFAULT 'CNY' COMMENT '币种',
    source_type VARCHAR(32) NOT NULL COMMENT 'QUOTE、PUBLIC、MANUAL、IMPORT',
    source_file_id BIGINT UNSIGNED NULL COMMENT '来源文件 ID',
    source_ref VARCHAR(255) NULL COMMENT '外部来源引用',
    quality_status VARCHAR(20) NOT NULL DEFAULT 'UNREVIEWED' COMMENT 'UNREVIEWED、VALID、INVALID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_market_price_product_date (product_id, quote_date),
    KEY idx_market_price_supplier_date (supplier_id, quote_date),
    KEY idx_market_price_quality (quality_status, quote_date),
    CONSTRAINT fk_market_price_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_market_price_supplier FOREIGN KEY (supplier_id) REFERENCES suppliers (id),
    CONSTRAINT fk_market_price_unit FOREIGN KEY (unit_id) REFERENCES md_units (id),
    CONSTRAINT fk_market_price_file FOREIGN KEY (source_file_id) REFERENCES sys_files (id),
    CONSTRAINT chk_market_price_values CHECK (price >= 0 AND (quantity_from IS NULL OR quantity_from > 0) AND (quantity_to IS NULL OR quantity_to > 0) AND (quantity_from IS NULL OR quantity_to IS NULL OR quantity_from <= quantity_to))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='历史价格记录';

CREATE TABLE price_forecast_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    product_id BIGINT UNSIGNED NOT NULL COMMENT '预测产品 ID',
    train_start_date DATE NOT NULL COMMENT '训练数据开始日期',
    train_end_date DATE NOT NULL COMMENT '训练数据结束日期',
    model_version VARCHAR(64) NOT NULL COMMENT '模型版本',
    forecast_horizon_days INT UNSIGNED NOT NULL COMMENT '预测天数',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、RUNNING、SUCCEEDED、FAILED',
    result_file_id BIGINT UNSIGNED NULL COMMENT '结果报告文件 ID',
    started_at DATETIME(3) NULL COMMENT '开始时间',
    finished_at DATETIME(3) NULL COMMENT '结束时间',
    error_message VARCHAR(2000) NULL COMMENT '失败信息',
    created_by BIGINT UNSIGNED NOT NULL COMMENT '创建任务用户 ID',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_forecast_product_status (product_id, status, created_at),
    KEY idx_forecast_status_created (status, created_at),
    CONSTRAINT fk_forecast_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_forecast_result_file FOREIGN KEY (result_file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_forecast_creator FOREIGN KEY (created_by) REFERENCES sys_users (id),
    CONSTRAINT chk_forecast_dates CHECK (train_start_date <= train_end_date AND forecast_horizon_days > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格预测任务';

CREATE TABLE price_forecast_items (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    run_id BIGINT UNSIGNED NOT NULL COMMENT '预测任务 ID',
    forecast_date DATE NOT NULL COMMENT '预测日期',
    predicted_price DECIMAL(18,6) NOT NULL COMMENT '预测价格',
    lower_bound DECIMAL(18,6) NULL COMMENT '预测区间下界',
    upper_bound DECIMAL(18,6) NULL COMMENT '预测区间上界',
    confidence DECIMAL(5,4) NULL COMMENT '置信度，0 到 1',
    explanation VARCHAR(2000) NULL COMMENT '解释信息',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_forecast_item_date (run_id, forecast_date),
    KEY idx_forecast_item_date (forecast_date),
    CONSTRAINT fk_forecast_item_run FOREIGN KEY (run_id) REFERENCES price_forecast_runs (id),
    CONSTRAINT chk_forecast_item_price CHECK (predicted_price >= 0 AND (lower_bound IS NULL OR lower_bound >= 0) AND (upper_bound IS NULL OR upper_bound >= 0) AND (confidence IS NULL OR confidence BETWEEN 0 AND 1) AND (lower_bound IS NULL OR upper_bound IS NULL OR lower_bound <= upper_bound))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格预测明细';

CREATE TABLE ai_conversations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    user_id BIGINT UNSIGNED NOT NULL COMMENT '发起用户 ID',
    title VARCHAR(255) NULL COMMENT '会话标题',
    business_scene VARCHAR(64) NOT NULL COMMENT '业务场景，例如 PRODUCT_SEARCH、QUOTE_COMPARE',
    permission_snapshot JSON NOT NULL COMMENT '会话开始时的权限快照',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE、ARCHIVED、CLOSED',
    last_message_at DATETIME(3) NULL COMMENT '最近消息时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    KEY idx_ai_conversation_user_status (user_id, status, last_message_at),
    CONSTRAINT fk_ai_conversation_user FOREIGN KEY (user_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 会话';

CREATE TABLE ai_messages (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    conversation_id BIGINT UNSIGNED NOT NULL COMMENT '会话 ID',
    message_role VARCHAR(20) NOT NULL COMMENT 'USER、ASSISTANT、SYSTEM、TOOL',
    content LONGTEXT NOT NULL COMMENT '消息内容',
    citations JSON NULL COMMENT '引用来源、业务编号、文件页码等',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '消息时间',
    PRIMARY KEY (id),
    KEY idx_ai_message_conversation_time (conversation_id, created_at),
    CONSTRAINT fk_ai_message_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 消息';

CREATE TABLE ai_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    conversation_id BIGINT UNSIGNED NOT NULL COMMENT '会话 ID',
    trigger_message_id BIGINT UNSIGNED NULL COMMENT '触发本次运行的消息 ID',
    model_name VARCHAR(128) NOT NULL COMMENT '模型名称',
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING、SUCCEEDED、FAILED、CANCELLED',
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '开始时间',
    finished_at DATETIME(3) NULL COMMENT '结束时间',
    duration_ms BIGINT UNSIGNED NULL COMMENT '耗时毫秒',
    error_message VARCHAR(2000) NULL COMMENT '错误信息',
    input_summary TEXT NULL COMMENT '输入摘要，不保存不必要的敏感原文',
    output_summary TEXT NULL COMMENT '输出摘要',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    KEY idx_ai_run_conversation_time (conversation_id, started_at),
    KEY idx_ai_run_status_time (status, started_at),
    CONSTRAINT fk_ai_run_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations (id),
    CONSTRAINT fk_ai_run_message FOREIGN KEY (trigger_message_id) REFERENCES ai_messages (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 运行';

CREATE TABLE ai_run_steps (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    run_id BIGINT UNSIGNED NOT NULL COMMENT 'AI 运行 ID',
    step_no INT UNSIGNED NOT NULL COMMENT '步骤顺序号',
    step_name VARCHAR(128) NOT NULL COMMENT '步骤名称',
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING、SUCCEEDED、FAILED、SKIPPED',
    input_summary TEXT NULL COMMENT '输入摘要',
    output_summary TEXT NULL COMMENT '输出摘要',
    duration_ms BIGINT UNSIGNED NULL COMMENT '耗时毫秒',
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '开始时间',
    finished_at DATETIME(3) NULL COMMENT '结束时间',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_step_no (run_id, step_no),
    KEY idx_ai_step_status (run_id, status),
    CONSTRAINT fk_ai_step_run FOREIGN KEY (run_id) REFERENCES ai_runs (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 运行步骤';

CREATE TABLE ai_tool_calls (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    run_step_id BIGINT UNSIGNED NOT NULL COMMENT 'AI 步骤 ID',
    tool_name VARCHAR(128) NOT NULL COMMENT '工具名称',
    arguments_json JSON NULL COMMENT '结构化工具参数，敏感字段应脱敏',
    permission_status VARCHAR(20) NOT NULL COMMENT 'ALLOWED、DENIED、ERROR',
    permission_snapshot JSON NULL COMMENT '本次调用的权限判断快照',
    result_summary TEXT NULL COMMENT '返回摘要',
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING、SUCCEEDED、FAILED、DENIED',
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '开始时间',
    finished_at DATETIME(3) NULL COMMENT '结束时间',
    duration_ms BIGINT UNSIGNED NULL COMMENT '耗时毫秒',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (id),
    KEY idx_ai_tool_name_status (tool_name, status, created_at),
    KEY idx_ai_tool_step (run_step_id, created_at),
    CONSTRAINT fk_ai_tool_step FOREIGN KEY (run_step_id) REFERENCES ai_run_steps (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 工具调用';

CREATE TABLE ai_action_approvals (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    tool_call_id BIGINT UNSIGNED NULL COMMENT '来源工具调用 ID',
    action_type VARCHAR(64) NOT NULL COMMENT '动作类型，例如 CREATE_PURCHASE_ORDER',
    target_type VARCHAR(64) NULL COMMENT '目标对象类型',
    target_id BIGINT UNSIGNED NULL COMMENT '目标对象 ID，草稿尚未落库时为空',
    draft_payload JSON NOT NULL COMMENT '待用户确认的动作草稿',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING、APPROVED、REJECTED、EXECUTED、EXPIRED、CANCELLED',
    requested_by BIGINT UNSIGNED NOT NULL COMMENT '申请确认用户 ID',
    approved_by BIGINT UNSIGNED NULL COMMENT '审批/确认用户 ID',
    requested_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '申请时间',
    approved_at DATETIME(3) NULL COMMENT '确认时间',
    executed_at DATETIME(3) NULL COMMENT '执行时间',
    approval_comment VARCHAR(2000) NULL COMMENT '审批意见',
    execution_result JSON NULL COMMENT '执行结果摘要',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_action_tool_call (tool_call_id),
    KEY idx_ai_action_target_status (target_type, target_id, status),
    KEY idx_ai_action_requester_status (requested_by, status),
    CONSTRAINT fk_ai_action_tool_call FOREIGN KEY (tool_call_id) REFERENCES ai_tool_calls (id),
    CONSTRAINT fk_ai_action_requester FOREIGN KEY (requested_by) REFERENCES sys_users (id),
    CONSTRAINT fk_ai_action_approver FOREIGN KEY (approved_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI 动作确认与审批';

CREATE TABLE sys_audit_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    actor_id BIGINT UNSIGNED NULL COMMENT '操作用户 ID，系统任务可为空',
    action_type VARCHAR(64) NOT NULL COMMENT '操作类型，例如 CREATE、UPDATE、EXPORT、LOGIN、FILE_ACCESS',
    resource_type VARCHAR(64) NOT NULL COMMENT '资源类型',
    resource_id BIGINT UNSIGNED NULL COMMENT '资源 ID',
    request_summary TEXT NULL COMMENT '请求摘要，不记录密码、密钥和文件原文',
    result_status VARCHAR(20) NOT NULL COMMENT 'SUCCESS、FAILED、DENIED',
    ip_address VARCHAR(45) NULL COMMENT '客户端 IPv4/IPv6 地址',
    user_agent VARCHAR(500) NULL COMMENT '客户端信息',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '审计时间',
    PRIMARY KEY (id),
    KEY idx_audit_actor_time (actor_id, created_at),
    KEY idx_audit_resource_time (resource_type, resource_id, created_at),
    KEY idx_audit_action_time (action_type, created_at),
    KEY idx_audit_result_time (result_status, created_at),
    CONSTRAINT fk_audit_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统审计日志';

ALTER TABLE sys_departments
    ADD CONSTRAINT fk_department_manager FOREIGN KEY (manager_id) REFERENCES sys_users (id);

SET FOREIGN_KEY_CHECKS = 1;
