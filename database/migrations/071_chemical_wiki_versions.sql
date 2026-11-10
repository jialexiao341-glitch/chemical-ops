-- 记录百科维护版本与原文快照，保留来源及维护人。
CREATE TABLE IF NOT EXISTS chemical_wiki_versions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    entry_id INT NOT NULL,
    version INT NOT NULL,
    content JSON NOT NULL,
    note TEXT NOT NULL,
    actor_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_chemical_wiki_entry_version (entry_id, version),
    KEY ix_chemical_wiki_versions_entry_id (entry_id),
    CONSTRAINT fk_chemical_wiki_version_actor FOREIGN KEY (actor_id) REFERENCES sys_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='化学品百科版本';
