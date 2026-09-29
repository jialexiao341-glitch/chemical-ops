CREATE TABLE quality_inspection_standards (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id BIGINT UNSIGNED NOT NULL,
    version_no INT NOT NULL,
    source_reference VARCHAR(255) NOT NULL,
    criteria JSON NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_quality_standard_version (product_id, version_no),
    CONSTRAINT fk_quality_standard_product FOREIGN KEY (product_id) REFERENCES md_products (id),
    CONSTRAINT fk_quality_standard_creator FOREIGN KEY (created_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人工维护的产品检测标准版本';

CREATE TABLE quality_report_reviews (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    acceptance_id BIGINT UNSIGNED NOT NULL,
    delivery_item_id BIGINT UNSIGNED NOT NULL,
    file_id BIGINT UNSIGNED NOT NULL,
    standard_id BIGINT UNSIGNED NULL,
    result_json JSON NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    reviewer_note VARCHAR(2000) NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    reviewed_by BIGINT UNSIGNED NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    reviewed_at DATETIME(3) NULL,
    PRIMARY KEY (id),
    KEY idx_quality_review_acceptance (acceptance_id, created_at),
    CONSTRAINT fk_quality_review_acceptance FOREIGN KEY (acceptance_id) REFERENCES quality_acceptances (id),
    CONSTRAINT fk_quality_review_delivery_item FOREIGN KEY (delivery_item_id) REFERENCES delivery_items (id),
    CONSTRAINT fk_quality_review_file FOREIGN KEY (file_id) REFERENCES sys_files (id),
    CONSTRAINT fk_quality_review_standard FOREIGN KEY (standard_id) REFERENCES quality_inspection_standards (id),
    CONSTRAINT fk_quality_review_creator FOREIGN KEY (created_by) REFERENCES sys_users (id),
    CONSTRAINT fk_quality_review_reviewer FOREIGN KEY (reviewed_by) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='验收报告核对与人工复核历史';
