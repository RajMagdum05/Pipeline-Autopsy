CREATE TABLE IF NOT EXISTS document_semantic_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processed_document_id UUID NOT NULL REFERENCES processed_documents(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    input_checksum_sha256 VARCHAR(64) NOT NULL,
    attempt_number INTEGER NOT NULL,
    artifact_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_id TEXT,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    error_code TEXT,
    CONSTRAINT uq_document_semantic_artifact_kind UNIQUE (processed_document_id, artifact_kind)
);
CREATE INDEX IF NOT EXISTS ix_document_semantic_artifacts_claim_id ON document_semantic_artifacts (claim_id);
CREATE INDEX IF NOT EXISTS ix_document_semantic_artifacts_document_id ON document_semantic_artifacts (document_id);
CREATE INDEX IF NOT EXISTS ix_document_semantic_artifacts_processed_document_id ON document_semantic_artifacts (processed_document_id);
