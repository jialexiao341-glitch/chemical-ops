-- 评测结果入库：按月回答“这个月比上个月稳了还是退步”。
-- 幂等键为 envelope 文件指纹；同一 envelope 重复登记直接跳过。
CREATE TABLE IF NOT EXISTS ai_eval_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    envelope_sha256 CHAR(64) NOT NULL,
    suite VARCHAR(16) NOT NULL,
    prompt_key VARCHAR(128) NULL,
    model VARCHAR(64) NULL,
    code_revision VARCHAR(64) NULL,
    dataset_sha256 CHAR(64) NULL,
    repeat_count INT NOT NULL DEFAULT 1,
    cases_total INT NOT NULL DEFAULT 0,
    stable_pass INT NOT NULL DEFAULT 0,
    unstable INT NOT NULL DEFAULT 0,
    stable_fail INT NOT NULL DEFAULT 0,
    no_evidence INT NOT NULL DEFAULT 0,
    excluded_infra INT NOT NULL DEFAULT 0,
    verdict VARCHAR(16) NOT NULL,
    collected_at DATETIME(3) NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uq_ai_eval_runs_envelope (envelope_sha256),
    KEY ix_ai_eval_runs_suite_collected (suite, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测 envelope 摘要';

CREATE TABLE IF NOT EXISTS ai_eval_case_results (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id BIGINT UNSIGNED NOT NULL,
    case_key VARCHAR(191) NOT NULL,
    safety TINYINT(1) NOT NULL DEFAULT 0,
    trials INT NOT NULL DEFAULT 0,
    passed INT NOT NULL DEFAULT 0,
    excluded_infra INT NOT NULL DEFAULT 0,
    verdict VARCHAR(16) NOT NULL,
    failed_checks JSON NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_ai_eval_case_run_key (run_id, case_key),
    KEY ix_ai_eval_case_verdict (verdict),
    CONSTRAINT fk_ai_eval_case_run FOREIGN KEY (run_id) REFERENCES ai_eval_runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测逐用例稳定性结果';