-- 保存可安全回放的 JSON 响应头，保留 Location、ETag 等语义信息。

ALTER TABLE sys_idempotency_records
    ADD COLUMN response_headers JSON NULL;
