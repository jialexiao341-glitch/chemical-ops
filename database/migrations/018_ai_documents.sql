-- ChemicalOps AI 文档知识库：TDS/MSDS 解析清洗后的文档与章节表。
-- 原件保留在 MinIO（chemicalops-msds / chemicalops-tds），本表只存解析结果与质检状态。

CREATE TABLE IF NOT EXISTS ai_documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cas_no VARCHAR(32) NOT NULL,
    doc_type VARCHAR(16) NOT NULL COMMENT 'msds | tds | property',
    title VARCHAR(255) NULL COMMENT '英文名（来自页面标题）',
    name_zh VARCHAR(128) NULL COMMENT '中文名（按 CAS 关联 md_chemicals）',
    source_bucket VARCHAR(64) NOT NULL,
    object_key VARCHAR(255) NOT NULL,
    source_url VARCHAR(512) NULL,
    parse_status VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PARSED | THIN | REJECTED | PENDING',
    reject_reason VARCHAR(255) NULL,
    section_count INT NOT NULL DEFAULT 0,
    char_count INT NOT NULL DEFAULT 0,
    meta_json JSON NULL COMMENT '同义词/分子式/分子量/GHS/UN 号等结构化元数据',
    sha256 VARCHAR(64) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_doc_cas_type (cas_no, doc_type),
    KEY idx_ai_doc_status (parse_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_document_sections (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    document_id BIGINT UNSIGNED NOT NULL,
    cas_no VARCHAR(32) NOT NULL,
    doc_type VARCHAR(16) NOT NULL,
    section_no INT NULL COMMENT 'SDS 的 SECTION 序号 / PDF 页码；物性页为 NULL',
    section_key VARCHAR(64) NOT NULL,
    title VARCHAR(255) NULL,
    content MEDIUMTEXT NOT NULL,
    char_count INT NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_ai_section_doc (document_id),
    KEY idx_ai_section_cas (cas_no),
    CONSTRAINT fk_ai_section_document FOREIGN KEY (document_id) REFERENCES ai_documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
